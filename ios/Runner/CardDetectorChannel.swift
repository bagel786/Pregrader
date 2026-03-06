import Flutter
import Vision
import UIKit

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
            default:
                result(FlutterMethodNotImplemented)
            }
        }
    }

    private static func detectRectangle(imagePath: String, result: @escaping FlutterResult) {
        guard let image = UIImage(contentsOfFile: imagePath),
              let cgImage = image.cgImage else {
            result(nil) // No image — return nil (fallback on Flutter side)
            return
        }

        let request = VNDetectRectanglesRequest { request, error in
            if let error = error {
                result(nil)
                return
            }

            guard let observations = request.results as? [VNRectangleObservation],
                  let rect = observations.first else {
                result(nil) // No rectangle found
                return
            }

            // VNRectangleObservation gives normalized coords with origin at bottom-left.
            // Flutter expects origin at top-left, so flip Y.
            let detected: [String: Double] = [
                "left": Double(rect.boundingBox.origin.x),
                "top": Double(1.0 - rect.boundingBox.origin.y - rect.boundingBox.height),
                "right": Double(rect.boundingBox.origin.x + rect.boundingBox.width),
                "bottom": Double(1.0 - rect.boundingBox.origin.y),
                "confidence": Double(rect.confidence),
                // Also send the four corners for potential perspective correction
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

        // Configure for card-like rectangles
        request.minimumAspectRatio = 0.55
        request.maximumAspectRatio = 0.85
        request.minimumSize = 0.1  // Card must be at least 10% of frame
        request.minimumConfidence = 0.5
        request.maximumObservations = 1  // We only want the best match

        let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
        DispatchQueue.global(qos: .userInitiated).async {
            do {
                try handler.perform([request])
            } catch {
                result(nil)
            }
        }
    }
}
