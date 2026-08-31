import Foundation

enum AppRoute: Hashable {
    case savedPosts(TripSession)
    case swipe(TripSession)
    case shortlist(TripSession)
    case lodging(TripSession)
    case itinerary(TripSession)
}
