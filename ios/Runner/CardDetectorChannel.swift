import Flutter
import Vision
import UIKit
import CoreVideo

class CardDetectorChannel {
    static func register(with messenger: FlutterBinaryMessenger) {
        let channel = FlutterMethodChannel(
            name: "com.pregrader/card_detector",
            binaryMessenger: messenger
        )
        channel.setMethodCallHandler { call, result in
            switch call.method {
            case "detectRectangle":
                guard let args = call.arguments as? [String: Any],
                      let imagePath = args["imagePath"] as? String else {
                    result(FlutterError(code: "INVALID_ARGS", message: "Missing imagePath", details: nil))
                    return
                }
                detectRectangle(imagePath: imagePath, result: result)

            case "detectRectangleFromBuffer":
                guard let args = call.arguments as? [String: Any],
                      let bytesData = args["bytes"] as? FlutterStandardTypedData,
                      let width = args["width"] as? Int,
                      let height = args["height"] as? Int,
                      let bytesPerRow = args["bytesPerRow"] as? Int else {
                    result(FlutterError(code: "INVALID_ARGS", message: "Missing buffer args", details: nil))
                    return
                }
                detectRectangleFromBuffer(
                    bytes: bytesData.data,
                    width: width,
                    height: height,
                    bytesPerRow: bytesPerRow,
                    result: result
                )

            default:
                result(FlutterMethodNotImplemented)
            }
        }
    }

    // MARK: - Detect from file path (used for captured photos)

    private static func detectRectangle(imagePath: String, result: @escaping FlutterResult) {
        let url = URL(fileURLWithPath: imagePath)
        guard let ciImage = CIImage(contentsOf: url) else {
            result(nil)
            return
        }

        let request = makeRectangleRequest(result: result)
        let handler = VNImageRequestHandler(ciImage: ciImage, options: [:])
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try handler.perform([request])
            } catch {
                result(nil)
            }
        }
    }

    // MARK: - Detect from raw BGRA pixel buffer (used for live camera frames)

    private static func detectRectangleFromBuffer(
        bytes: Data,
        width: Int,
        height: Int,
        bytesPerRow: Int,
        result: @escaping FlutterResult
    ) {
        // Create CVPixelBuffer from the raw BGRA bytes
        var pixelBuffer: CVPixelBuffer?
        let attrs: [String: Any] = [
            kCVPixelBufferCGImageCompatibilityKey as String: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
        ]
        let status = CVPixelBufferCreate(
            kCFAllocatorDefault,
            width,
            height,
            kCVPixelFormatType_32BGRA,
            attrs as CFDictionary,
            &pixelBuffer
        )
        guard status == kCVReturnSuccess, let buffer = pixelBuffer else {
            result(nil)
            return
        }

        // Copy pixel data into the buffer
        CVPixelBufferLockBaseAddress(buffer, [])
        let destBase = CVPixelBufferGetBaseAddress(buffer)!
        let destBytesPerRow = CVPixelBufferGetBytesPerRow(buffer)

        bytes.withUnsafeBytes { srcPtr in
            guard let srcBase = srcPtr.baseAddress else { return }
            if destBytesPerRow == bytesPerRow {
                memcpy(destBase, srcBase, min(bytes.count, height * destBytesPerRow))
            } else {
                for row in 0..<height {
                    let srcOffset = row * bytesPerRow
                    let dstOffset = row * destBytesPerRow
                    memcpy(destBase + dstOffset, srcBase + srcOffset, min(bytesPerRow, destBytesPerRow))
                }
            }
        }
        CVPixelBufferUnlockBaseAddress(buffer, [])

        let request = makeRectangleRequest(result: result)

        // Camera frames are landscape (sensor orientation).
        // .right tells Vision the image should be rotated 90° CW to portrait,
        // so returned coords are in portrait space matching the screen.
        let handler = VNImageRequestHandler(cvPixelBuffer: buffer, orientation: .right, options: [:])
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try handler.perform([request])
            } catch {
                result(nil)
            }
        }
    }

    // MARK: - Shared request builder

    private static func makeRectangleRequest(result: @escaping FlutterResult) -> VNDetectRectanglesRequest {
        let request = VNDetectRectanglesRequest { request, error in
            if error != nil {
                result(nil)
                return
            }

            guard let observations = request.results as? [VNRectangleObservation],
                  let rect = observations.first else {
                result(nil)
                return
            }

            // VNRectangleObservation: normalized coords, origin at bottom-left.
            // Flutter expects origin at top-left, so flip Y.
            let detected: [String: Double] = [
                "left": Double(rect.boundingBox.origin.x),
                "top": Double(1.0 - rect.boundingBox.origin.y - rect.boundingBox.height),
                "right": Double(rect.boundingBox.origin.x + rect.boundingBox.width),
                "bottom": Double(1.0 - rect.boundingBox.origin.y),
                "confidence": Double(rect.confidence),
                "topLeftX": Double(rect.topLeft.x),
                "topLeftY": Double(1.0 - rect.topLeft.y),
                "topRightX": Double(rect.topRight.x),
                "topRightY": Double(1.0 - rect.topRight.y),
                "bottomLeftX": Double(rect.bottomLeft.x),
                "bottomLeftY": Double(1.0 - rect.bottomLeft.y),
                "bottomRightX": Double(rect.bottomRight.x),
                "bottomRightY": Double(1.0 - rect.bottomRight.y),
            ]
            result(detected)
        }

        request.minimumAspectRatio = 0.55
        request.maximumAspectRatio = 0.85
        request.minimumSize = 0.1
        request.minimumConfidence = 0.3
        request.maximumObservations = 1

        return request
    }
}
