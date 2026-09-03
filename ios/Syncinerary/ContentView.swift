import SwiftUI

struct ContentView: View {
    /// A code the person arrived with. Sending them straight to join skips
    /// re-typing what they already tapped.
    var openingInvite: String?

    @Environment(AccountStore.self) private var accounts

    @State private var path: [AppRoute] = []
    @State private var recentTrips = RecentTripsStore()
    @State private var resumeErrorMessage = ""
    @State private var isShowingResumeError = false

    var body: some View {
        NavigationStack(path: $path) {
            TripsBoardView(
                onOpen: open,
                onCreate: { path.append(.newTrip) },
                onJoin: { path.append(.joinTrip(nil)) }
            )
                .navigationDestination(for: AppRoute.self) { route in
                    switch route {
                    case .newTrip:
                        TripCreateView(onCreated: startGathering, onResume: resume)
                    case let .joinTrip(code):
                        JoinTripView(prefilledCode: code, onJoined: joined)
                    case let .invite(trip):
                        InviteView(trip: trip)
                    case let .chat(trip):
                        TripChatView(trip: trip)
                    case let .gathering(session):
                        GatheringView(session: session, onGathered: showSavedPosts)
                    case let .savedPosts(session):
                        SavedPostsView(session: session, onContinue: showSwipe)
                    case let .swipe(session):
                        SwipeView(session: session, onVotingComplete: showShortlist)
                    case let .shortlist(session):
                        ShortlistView(session: session, onConfirmed: showLodging)
                    case let .lodging(session):
                        LodgingView(session: session, onPlanned: showItinerary)
                    case let .itinerary(session):
                        ItineraryView(session: session)
                    }
                }
        }
        .environment(recentTrips)
        .tint(AppTheme.ink)
        .task {
            if let openingInvite, path.isEmpty {
                path.append(.joinTrip(openingInvite))
                return
            }
            resumeFromLaunchArguments()
        }
        .alert("Couldn't reopen this trip", isPresented: $isShowingResumeError) { } message: {
            Text(resumeErrorMessage)
        }
    }

    /// Development only: `-SYNC_RESUME_TRIP_ID <uuid>` as a launch argument
    /// (or the same UserDefaults key) reopens a saved trip straight away, so
    /// a screen can be reached without tapping through the flow.
    private func resumeFromLaunchArguments() {
        guard path.isEmpty,
              let wanted = UserDefaults.standard.string(forKey: "SYNC_RESUME_TRIP_ID"),
              let session = recentTrips.sessions.first(where: {
                  $0.trip.id.uuidString.caseInsensitiveCompare(wanted) == .orderedSame
              }) else {
            return
        }
        resume(session)
    }

    /// A trip from the board. The thread is the way in, because that is
    /// where the group is already talking and dropping links.
    private func open(_ trip: TripListRow) {
        path.append(.chat(trip))
    }

    private func joined(_ response: JoinTripResponse) {
        Task {
            await accounts.loadTrips()
            if let row = accounts.trips.first(where: { $0.id == response.trip.id }) {
                path.removeAll()
                path.append(.chat(row))
            }
        }
    }

    private func startGathering(_ session: TripSession) {
        recentTrips.remember(session)
        path.append(.gathering(session))
    }

    /// Ask the server where the trip stands now, then jump to that step.
    private func resume(_ session: TripSession) {
        if let forced = UserDefaults.standard.string(forKey: "SYNC_RESUME_ROUTE") {
            path.append(AppRoute.resume(session, forced: forced))
            return
        }
        Task {
            do {
                let trip = try await APIClient.shared.trip(tripID: session.trip.id)
                let refreshed = recentTrips.refresh(session, with: trip)
                path.append(AppRoute.resume(refreshed))
            } catch {
                resumeErrorMessage = error.localizedDescription
                isShowingResumeError = true
            }
        }
    }

    private func showSavedPosts(_ session: TripSession) {
        path.append(.savedPosts(session))
    }

    private func showSwipe(_ session: TripSession) {
        path.append(.swipe(session))
    }

    private func showShortlist(_ session: TripSession) {
        path.append(.shortlist(session))
    }

    private func showLodging(_ session: TripSession) {
        path.append(.lodging(session))
    }

    private func showItinerary(_ session: TripSession) {
        path.append(.itinerary(session))
    }
}

#Preview {
    ContentView()
}
