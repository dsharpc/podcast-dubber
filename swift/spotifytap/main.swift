// spotifytap: record Spotify's audio output to a file using a Core Audio process tap.
//
// Usage: spotifytap <output.caf> [--silence-timeout SECONDS] [--max-minutes N] [--bundle-prefix ID]
//
// Stops cleanly on SIGINT/SIGTERM, after `--silence-timeout` seconds of silence once audio
// has been heard (0 disables), or after `--max-minutes`. Requires macOS 14.4+ and the
// "Screen & System Audio Recording" permission for the host terminal.

import AVFoundation
import CoreAudio
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("spotifytap: \(message)\n".utf8))
    exit(1)
}

func log(_ message: String) {
    FileHandle.standardError.write(Data("\(message)\n".utf8))
}

func check(_ status: OSStatus, _ what: String) {
    if status != noErr { fail("\(what) failed (OSStatus \(status))") }
}

// MARK: - Arguments

var outputPath: String?
var silenceTimeout = 30.0
var maxMinutes = 0.0
var bundlePrefix = "com.spotify.client"

var listOnly = false

var args = CommandLine.arguments.dropFirst()
while let arg = args.popFirst() {
    switch arg {
    case "--list":
        listOnly = true
    case "--silence-timeout":
        guard let v = args.popFirst().flatMap(Double.init) else { fail("--silence-timeout needs a number") }
        silenceTimeout = v
    case "--max-minutes":
        guard let v = args.popFirst().flatMap(Double.init) else { fail("--max-minutes needs a number") }
        maxMinutes = v
    case "--bundle-prefix":
        guard let v = args.popFirst() else { fail("--bundle-prefix needs a value") }
        bundlePrefix = v
    default:
        if outputPath == nil { outputPath = arg } else { fail("unexpected argument: \(arg)") }
    }
}
guard let outputPath = outputPath ?? (listOnly ? "" : nil) else {
    fail("usage: spotifytap <output.caf> [--silence-timeout SECONDS] [--max-minutes N] [--bundle-prefix ID]")
}

// MARK: - Core Audio helpers

func getProperty<T>(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector, as type: T.Type, default value: T) -> T? {
    var address = AudioObjectPropertyAddress(
        mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var size = UInt32(MemoryLayout<T>.size)
    var result = value
    let status = withUnsafeMutablePointer(to: &result) {
        AudioObjectGetPropertyData(object, &address, 0, nil, &size, $0)
    }
    return status == noErr ? result : nil
}

func processObjects() -> [AudioObjectID] {
    var address = AudioObjectPropertyAddress(
        mSelector: kAudioHardwarePropertyProcessObjectList,
        mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    check(AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size), "list audio processes")
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    check(AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &address, 0, nil, &size, &ids), "read audio processes")
    return ids
}

func bundleID(of process: AudioObjectID) -> String? {
    let value: CFString? = getProperty(process, kAudioProcessPropertyBundleID, as: CFString?.self, default: nil) ?? nil
    return value as String?
}

// MARK: - Find Spotify

if listOnly {
    for p in processObjects() {
        let pid = getProperty(p, kAudioProcessPropertyPID, as: pid_t.self, default: 0) ?? 0
        let output = getProperty(p, kAudioProcessPropertyIsRunningOutput, as: UInt32.self, default: 0) ?? 0
        print("object \(p) pid \(pid) output=\(output) \(bundleID(of: p) ?? "?")")
    }
    exit(0)
}

let spotifyProcesses = processObjects().filter { bundleID(of: $0)?.hasPrefix(bundlePrefix) == true }
guard !spotifyProcesses.isEmpty else {
    fail("no running audio process matching '\(bundlePrefix)'. Open Spotify and start playback first.")
}
log("Tapping \(spotifyProcesses.count) Spotify audio process(es)")
let playing = spotifyProcesses.contains { (getProperty($0, kAudioProcessPropertyIsRunningOutput, as: UInt32.self, default: 0) ?? 0) != 0 }
if !playing { log("Warning: Spotify is not producing audio right now. Press play.") }

// MARK: - Tap + aggregate device

let tapUUID = UUID()
let tapDescription = CATapDescription(stereoMixdownOfProcesses: spotifyProcesses)
tapDescription.uuid = tapUUID
tapDescription.name = "spotifytap"
tapDescription.muteBehavior = .unmuted  // keep Spotify audible while recording
tapDescription.isPrivate = true

var tapID = AudioObjectID(kAudioObjectUnknown)
check(AudioHardwareCreateProcessTap(tapDescription, &tapID), "create process tap (grant audio recording permission to your terminal?)")

guard var tapFormat = getProperty(tapID, kAudioTapPropertyFormat, as: AudioStreamBasicDescription.self, default: AudioStreamBasicDescription()) else {
    fail("could not read tap format")
}

guard let outputDevice = getProperty(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyDefaultSystemOutputDevice, as: AudioObjectID.self, default: 0),
      let outputUID: CFString = getProperty(outputDevice, kAudioDevicePropertyDeviceUID, as: CFString?.self, default: nil) ?? nil
else { fail("could not determine default output device") }

let aggregateDescription: [String: Any] = [
    kAudioAggregateDeviceNameKey: "spotifytap-aggregate",
    kAudioAggregateDeviceUIDKey: UUID().uuidString,
    kAudioAggregateDeviceMainSubDeviceKey: outputUID as String,
    kAudioAggregateDeviceIsPrivateKey: true,
    kAudioAggregateDeviceIsStackedKey: false,
    kAudioAggregateDeviceTapAutoStartKey: true,
    kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outputUID as String]],
    kAudioAggregateDeviceTapListKey: [[
        kAudioSubTapDriftCompensationKey: true,
        kAudioSubTapUIDKey: tapUUID.uuidString,
    ]],
]

var aggregateID = AudioObjectID(kAudioObjectUnknown)
check(AudioHardwareCreateAggregateDevice(aggregateDescription as CFDictionary, &aggregateID), "create aggregate device")

// MARK: - Output file

guard let format = AVAudioFormat(streamDescription: &tapFormat) else { fail("unsupported tap format") }
let outputURL = URL(fileURLWithPath: outputPath)
let outputFile: AVAudioFile
do {
    outputFile = try AVAudioFile(
        forWriting: outputURL, settings: format.settings,
        commonFormat: .pcmFormatFloat32, interleaved: format.isInterleaved)
} catch {
    fail("cannot open \(outputPath): \(error.localizedDescription)")
}

// MARK: - Capture

let startTime = Date()
var heardAudio = false
var lastLoudTime = Date()
let silenceThreshold: Float = 0.0005  // ~ -66 dBFS peak
let ioQueue = DispatchQueue(label: "spotifytap.io", qos: .userInitiated)

var procID: AudioDeviceIOProcID?
check(AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, ioQueue) { _, inputData, _, _, _ in
    guard let buffer = AVAudioPCMBuffer(pcmFormat: format, bufferListNoCopy: inputData, deallocator: nil) else { return }
    do { try outputFile.write(from: buffer) } catch { log("write error: \(error.localizedDescription)") }

    var peak: Float = 0
    if let channels = buffer.floatChannelData {
        for c in 0..<Int(format.channelCount) {
            let samples = channels[c]
            for i in 0..<Int(buffer.frameLength) { peak = max(peak, abs(samples[i])) }
        }
    }
    if peak > silenceThreshold {
        heardAudio = true
        lastLoudTime = Date()
    }
}, "create IO proc")
check(AudioDeviceStart(aggregateID, procID), "start capture")
log("Recording to \(outputPath) ... (Ctrl-C to stop)")

// MARK: - Shutdown

var stopping = false
func stop(_ reason: String) {
    if stopping { return }
    stopping = true
    log("Stopping: \(reason)")
    AudioDeviceStop(aggregateID, procID)
    if let procID { AudioDeviceDestroyIOProcID(aggregateID, procID) }
    AudioHardwareDestroyAggregateDevice(aggregateID)
    AudioHardwareDestroyProcessTap(tapID)
    if !heardAudio {
        log("WARNING: the recording is completely silent. Either nothing was playing, or this terminal lacks")
        log("audio-recording permission (System Settings > Privacy & Security > Screen & System Audio Recording).")
        log("After granting it, fully quit and reopen the terminal app, then record again.")
    }
    let seconds = Int(Date().timeIntervalSince(startTime))
    log("Recorded \(seconds / 60)m\(seconds % 60)s")
    exit(0)
}

signal(SIGINT, SIG_IGN)
signal(SIGTERM, SIG_IGN)
let signalSources = [SIGINT, SIGTERM].map { sig -> DispatchSourceSignal in
    let source = DispatchSource.makeSignalSource(signal: sig, queue: .main)
    source.setEventHandler { stop("signal \(sig)") }
    source.resume()
    return source
}

let watchdog = DispatchSource.makeTimerSource(queue: .main)
watchdog.schedule(deadline: .now() + 1, repeating: 1)
watchdog.setEventHandler {
    let now = Date()
    if maxMinutes > 0, now.timeIntervalSince(startTime) > maxMinutes * 60 { stop("max duration reached") }
    if silenceTimeout > 0, heardAudio, now.timeIntervalSince(lastLoudTime) > silenceTimeout {
        stop("\(Int(silenceTimeout))s of silence")
    }
    let elapsed = Int(now.timeIntervalSince(startTime))
    if elapsed % 60 == 0 && elapsed > 0 { log("  \(elapsed / 60) min recorded\(heardAudio ? "" : " (no audio heard yet)")") }
}
watchdog.resume()

dispatchMain()
