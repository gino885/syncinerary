import Foundation

/// Where a trip is in its life, which is the only thing that decides which
/// screen opening it should land on.
///
/// The product advances with the trip: people talk before there is anything
/// to look at, then swipe, then confirm, then read the plan. Once an
/// itinerary exists it is the trip's main artifact, so opening the trip shows
/// it rather than making the traveler pass back through an earlier surface.
///
/// This mapping lives here, once. Trip-list taps, launch resume, join by
/// code, and anything added later (deep links, notifications) all read it,
/// because four copies of a status switch is four chances to disagree about
/// where a trip belongs.
enum TripStage: Hashable {
    /// Before there is anything to decide on, the thread is the trip.
    case discuss
    case gathering
    case savedPosts
    case swipe
    case shortlist
    case lodging
    case itinerary

    static func of(_ status: String) -> TripStage {
        switch status {
        // Server trip status (CLAUDE.md section 7).
        case "draft", "setup": .discuss
        case "swiping": .swipe
        case "shortlisting": .shortlist
        case "scheduling": .lodging
        case "active", "disrupted": .itinerary
        // Client step names, used by the -SYNC_RESUME_ROUTE override.
        case "chat", "discuss": .discuss
        case "gathering": .gathering
        case "savedPosts": .savedPosts
        case "swipe": .swipe
        case "shortlist": .shortlist
        case "lodging": .lodging
        case "itinerary": .itinerary
        default: .gathering
        }
    }
}

enum AppRoute: Hashable {
    case newTrip
    case joinTrip(String?)
    case invite(TripListRow)
    case chat(TripListRow)
    case preparation(TripSession)
    case gathering(TripSession)
    case savedPosts(TripSession)
    case swipe(TripSession)
    case shortlist(TripSession)
    case lodging(TripSession)
    case itinerary(TripSession)

    /// The server lifecycle controls where a saved trip reopens.
    /// Draft rooms remain available before a leader starts discovery.
    static func primary(
        for session: TripSession,
        row: TripListRow? = nil,
        forced: String? = nil
    ) -> AppRoute {
        switch TripStage.of(forced ?? session.trip.status) {
        case .discuss: .chat(row ?? TripListRow(session: session))
        case .gathering: .gathering(session)
        case .savedPosts: .savedPosts(session)
        case .swipe: .swipe(session)
        case .shortlist: .shortlist(session)
        case .lodging: .lodging(session)
        case .itinerary: .itinerary(session)
        }
    }

    /// Where a saved trip picks up. `forced` is a development override
    /// (`-SYNC_RESUME_ROUTE swipe`) so a screen can be opened for
    /// verification without tapping through the flow.
    static func resume(_ session: TripSession, forced: String? = nil) -> AppRoute {
        primary(for: session, forced: forced)
    }
}
