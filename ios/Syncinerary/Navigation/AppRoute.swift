import Foundation

enum AppRoute: Hashable {
    case savedPosts(TripSession)
    case swipe(TripSession)
    case itinerary(TripSession)
}
