import Foundation

struct HealthResponse: Decodable {
    let status: String
    let milestone: String
}

enum APIError: Error {
    case badStatus(Int)
}

final class APIClient {
    static let shared = APIClient()

    // For physical device testing, replace with your Mac's LAN IP.
    private let baseURL = URL(string: "http://localhost:8000")!

    func health() async throws -> HealthResponse {
        let url = baseURL.appendingPathComponent("health")
        let (data, response) = try await URLSession.shared.data(from: url)
        if let http = response as? HTTPURLResponse, http.statusCode != 200 {
            throw APIError.badStatus(http.statusCode)
        }
        return try JSONDecoder().decode(HealthResponse.self, from: data)
    }
}
