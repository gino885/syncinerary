struct TripCreateRequest: Encodable, Sendable {
    /// The cities the traveler typed, in order. The backend resolves each one
    /// and derives the trip's display name from them, so nothing here is
    /// chosen from a fixed list.
    let cities: [String]
    /// Canonical Google choices paired with `cities`, so the backend resolves
    /// exactly what the traveler selected instead of repeating a text guess.
    let cityPlaceIDs: [String]
    let cityDays: [Int]
    let priorityCityIndex: Int?
    /// One country per trip: it disambiguates repeated city names and keeps
    /// each city's days together instead of alternating across the trip.
    let country: String
    let startDate: String
    let endDate: String
    let creatorName: String
    let creatorHomeCity: String?
    let creatorInterests: [String]
    let creatorDietaryExcludes: [String]
    /// The group creator's app language. Shared search and generated trip
    /// content follow this value for the lifetime of the trip.
    let outputLocale: String

    init(
        cities: [String],
        cityPlaceIDs: [String],
        country: String,
        startDate: String,
        endDate: String,
        creatorName: String,
        creatorHomeCity: String?,
        creatorInterests: [String],
        creatorDietaryExcludes: [String],
        outputLocale: String,
        cityDays: [Int] = [],
        priorityCityIndex: Int? = nil
    ) {
        self.cities = cities
        self.cityPlaceIDs = cityPlaceIDs
        self.cityDays = cityDays
        self.priorityCityIndex = priorityCityIndex
        self.country = CountryIdentifier.canonicalCode(for: country)
        self.startDate = startDate
        self.endDate = endDate
        self.creatorName = creatorName
        self.creatorHomeCity = creatorHomeCity
        self.creatorInterests = creatorInterests
        self.creatorDietaryExcludes = creatorDietaryExcludes
        self.outputLocale = outputLocale
    }

    enum CodingKeys: String, CodingKey {
        case cities
        case cityPlaceIDs = "city_place_ids"
        case cityDays = "city_days"
        case priorityCityIndex = "priority_city_index"
        case country
        case startDate = "start_date"
        case endDate = "end_date"
        case creatorName = "creator_name"
        case creatorHomeCity = "creator_home_city"
        case creatorInterests = "creator_interests"
        case creatorDietaryExcludes = "creator_dietary_excludes"
        case outputLocale = "output_locale"
    }
}
