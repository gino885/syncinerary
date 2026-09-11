import Foundation

enum ItineraryTimelineEntry: Identifiable {
    case stop(ItineraryStop)
    case meal(MealBreak)

    var id: String {
        switch self {
        case .stop(let stop): "stop-\(stop.id)"
        case .meal(let meal): "meal-\(meal.id)"
        }
    }

    var startTime: String {
        switch self {
        case .stop(let stop): stop.startTime
        case .meal(let meal): meal.startTime
        }
    }
}
