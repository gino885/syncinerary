struct ItineraryDay: Decodable, Identifiable, Sendable {
    var id: Int { day }

    var mealBreaks: [MealBreak]? = nil

    enum CodingKeys: String, CodingKey {
        case day, date, stops
        case mealBreaks = "meal_breaks"
    }

    let day: Int
    let date: String
    let stops: [ItineraryStop]
}
