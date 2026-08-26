struct ItineraryDay: Decodable, Identifiable, Sendable {
    var id: Int { day }

    let day: Int
    let date: String
    let stops: [ItineraryStop]
}
