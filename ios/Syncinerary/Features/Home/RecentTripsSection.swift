import SwiftUI

/// The trips this phone started, resumable in one tap.
struct RecentTripsSection: View {
    let sessions: [TripSession]
    let onResume: (TripSession) -> Void
    let onForget: (TripSession) -> Void

    var body: some View {
        if !sessions.isEmpty {
            Section {
                ForEach(sessions, id: \.trip.id) { session in
                    Button {
                        onResume(session)
                    } label: {
                        RecentTripRow(session: session)
                    }
                    .buttonStyle(.plain)
                    .swipeActions(edge: .trailing) {
                        Button("Forget", systemImage: "trash", role: .destructive) {
                            onForget(session)
                        }
                    }
                }
            } header: {
                EyebrowText("Continue")
            }
        }
    }
}
