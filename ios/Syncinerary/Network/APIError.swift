import Foundation

enum APIError: LocalizedError, Sendable {
    case invalidResponse
    case badStatus(Int, String?)
    case decoding(String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            "The server returned an invalid response."
        case let .badStatus(code, detail):
            detail ?? "The server returned status \(code)."
        case let .decoding(detail):
            "The app could not read the server response: \(detail)"
        }
    }
}
