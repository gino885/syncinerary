import SwiftUI

struct ContentView: View {
    @State private var path: [AppRoute] = []

    var body: some View {
        NavigationStack(path: $path) {
            TripCreateView(onCreated: showSwipe)
                .navigationDestination(for: AppRoute.self) { route in
                    switch route {
                    case let .swipe(session):
                        SwipeView(session: session, onPlanned: showItinerary)
                    case let .itinerary(tripID):
                        ItineraryView(tripID: tripID)
                    }
                }
        }
    }

    private func showSwipe(_ session: TripSession) {
        path.append(.swipe(session))
    }

    private func showItinerary(_ tripID: UUID) {
        path.append(.itinerary(tripID))
    }
}

#Preview {
    ContentView()
}
