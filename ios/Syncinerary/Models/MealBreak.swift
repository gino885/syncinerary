import Foundation

struct MealBreak: Decodable, Identifiable, Sendable {
    var id: String { meal }
    let meal: String
    let startTime: String
    let endTime: String
    let nearbyURL: URL

    var title: String {
        switch meal {
        case "lunch": String(localized: "Lunch break")
        case "dinner": String(localized: "Dinner break")
        default: String(localized: "Meal break")
        }
    }

    enum CodingKeys: String, CodingKey {
        case meal
        case startTime = "start_time"
        case endTime = "end_time"
        case nearbyURL = "nearby_url"
    }
}
