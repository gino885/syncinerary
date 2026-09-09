import Foundation

struct ItineraryStop: Decodable, Identifiable, Sendable {
    var id: UUID { candidateID }

    var timeRange: String {
        String(localized: "\(startTime.prefix(5)) to \(endTime.prefix(5))")
    }

    /// What the leg into this stop is called out loud.
    ///
    /// Two claims only: routed, or approximate. The provider that answered is
    /// internal to the backend, so a second provider in its chain can never
    /// become a second wording here.
    var transitLabel: String {
        switch transitFromPrevMode {
        case "transit": String(localized: "public transit")
        case "transit_estimated": String(localized: "approx. public transit")
        case "walking", "walk": String(localized: "walk")
        case "walking_estimated": String(localized: "approx. walk")
        case let mode?: mode
        case nil: String(localized: "travel")
        }
    }

    /// "Lunch", "Dinner", "Breakfast", or nil for a stop that is not a meal.
    var mealLabel: String? {
        guard let mealSlot else { return nil }
        return String(localized: String.LocalizationValue(mealSlot.capitalized))
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
    let sourcePosts: [SourcePost]

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
        case sourcePosts = "source_posts"
    }
}
