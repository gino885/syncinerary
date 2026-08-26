struct TripCreateRequest: Encodable, Sendable {
    let destination: String
    let startDate: String
    let endDate: String
    let creatorName: String
    let creatorHomeCity: String?

    enum CodingKeys: String, CodingKey {
        case destination
        case startDate = "start_date"
        case endDate = "end_date"
        case creatorName = "creator_name"
        case creatorHomeCity = "creator_home_city"
    }
}
