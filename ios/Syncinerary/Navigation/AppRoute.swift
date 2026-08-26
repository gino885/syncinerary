import Foundation

enum AppRoute: Hashable {
    case swipe(TripSession)
    case itinerary(UUID)
}
