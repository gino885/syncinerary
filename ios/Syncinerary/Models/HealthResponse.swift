struct HealthResponse: Decodable, Sendable {
    let status: String
    let milestone: String
}
