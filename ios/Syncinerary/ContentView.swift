import SwiftUI

struct ContentView: View {
    @State private var path: [AppRoute] = []

    var body: some View {
        NavigationStack(path: $path) {
            TripCreateView(onCreated: showSavedPosts)
                .navigationDestination(for: AppRoute.self) { route in
                    switch route {
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
        .tint(.blue)
    }

    private func showSavedPosts(_ session: TripSession) {
        path.append(.savedPosts(session))
    }

    private func showSwipe(_ session: TripSession) {
        path.append(.swipe(session))
    }

    private func showItinerary(_ session: TripSession) {
        path.append(.itinerary(session))
    }

    private func showLodging(_ session: TripSession) {
        path.append(.lodging(session))
    }

    private func showShortlist(_ session: TripSession) {
        path.append(.shortlist(session))
    }
}

#Preview {
    ContentView()
}
