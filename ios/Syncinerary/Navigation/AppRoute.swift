import Foundation

enum AppRoute: Hashable {
    case gathering(TripSession)
    case savedPosts(TripSession)
    case swipe(TripSession)
    case shortlist(TripSession)
    case lodging(TripSession)
    case itinerary(TripSession)

    /// Where a saved trip picks up, from the status the server reports now.
    /// `forced` is a development override (`-SYNC_RESUME_ROUTE swipe`) so a
    /// screen can be opened directly for verification.
    static func resume(_ session: TripSession, forced: String? = nil) -> AppRoute {
        switch forced ?? session.trip.status {
        case "gathering": .gathering(session)
        case "savedPosts": .savedPosts(session)
        case "swipe": .swipe(session)
        case "shortlist": .shortlist(session)
        case "lodging": .lodging(session)
        case "itinerary": .itinerary(session)
        case "swiping": .swipe(session)
        case "shortlisting": .shortlist(session)
        case "scheduling": .lodging(session)
        case "active", "disrupted": .itinerary(session)
        default: .gathering(session)
        }
    }
}
