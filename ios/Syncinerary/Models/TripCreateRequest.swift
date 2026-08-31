struct TripCreateRequest: Encodable, Sendable {
    /// The cities the traveler typed, in order. The backend resolves each one
    /// and derives the trip's display name from them, so nothing here is
    /// chosen from a fixed list.
    let cities: [String]
    /// One country per trip: it disambiguates repeated city names and keeps
    /// each city's days together instead of alternating across the trip.
    let country: String
    let startDate: String
    let endDate: String
    let creatorName: String
    let creatorHomeCity: String?
    let creatorInterests: [String]
    let creatorDietaryExcludes: [String]

    enum CodingKeys: String, CodingKey {
        case cities
        case country
        case startDate = "start_date"
        case endDate = "end_date"
        case creatorName = "creator_name"
        case creatorHomeCity = "creator_home_city"
        case creatorInterests = "creator_interests"
        case creatorDietaryExcludes = "creator_dietary_excludes"
    }
}
