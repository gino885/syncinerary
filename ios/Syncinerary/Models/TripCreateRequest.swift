struct TripCreateRequest: Encodable, Sendable {
    let destination: String
    let startDate: String
    let endDate: String
    let creatorName: String
    let creatorHomeCity: String?
}
