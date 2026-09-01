import Foundation

struct ItineraryStop: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    var timeRange: String {
        "\(startTime.prefix(5)) to \(endTime.prefix(5))"
    }

    var transitLabel: String {
        if transitFromPrevMode == "transit_transitous" {
            "public transit"
        } else {
            transitFromPrevMode ?? "travel"
        }
    }

    var usesTransitous: Bool {
        transitFromPrevMode == "transit_transitous"
    }

    /// "Lunch", "Dinner", "Breakfast", or nil for a stop that is not a meal.
    var mealLabel: String? {
        guard let mealSlot else { return nil }
        return mealSlot.prefix(1).uppercased() + mealSlot.dropFirst()
    }

    let candidateID: UUID
    let name: String
    let area: String?
    let description: String?
    let descriptionSource: String?
    let startTime: String
    let endTime: String
    let transitFromPrevMin: Int
    let transitFromPrevMode: String?
    let mealSlot: String?
    let sourceBadges: [SourceBadge]

    enum CodingKeys: String, CodingKey {
        case candidateID = "candidate_id"
        case name
        case area
        case description
        case descriptionSource = "description_source"
        case startTime = "start_time"
        case endTime = "end_time"
        case transitFromPrevMin = "transit_from_prev_min"
        case transitFromPrevMode = "transit_from_prev_mode"
        case mealSlot = "meal_slot"
        case sourceBadges = "source_badges"
    }
}
