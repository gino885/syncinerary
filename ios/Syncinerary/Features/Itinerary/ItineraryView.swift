import SwiftUI

struct ItineraryView: View {
    @State private var viewModel: ItineraryViewModel

    init(session: TripSession) {
        _viewModel = State(initialValue: ItineraryViewModel(session: session))
    }

    var body: some View {
        @Bindable var viewModel = viewModel

        Group {
            if viewModel.isLoading && viewModel.itinerary == nil {
                ProgressView("Loading itinerary…")
            } else if let itinerary = viewModel.itinerary {
                List {
                    if viewModel.liveUpdatesUnavailable {
                        Label(
                            "Live trip updates are reconnecting",
                            systemImage: "wifi.exclamationmark"
                        )
                        .foregroundStyle(.secondary)
                    }

                    ForEach(itinerary.days) { day in
                        ItineraryDaySection(day: day)
                    }

                    WishlistSection(items: itinerary.wishlistNotPlaced)
                }
                .refreshable {
                    await viewModel.load()
                }
            } else {
                ContentUnavailableView(
                    "No itinerary",
                    systemImage: "calendar.badge.exclamationmark",
                    description: Text("The itinerary could not be loaded.")
                )
            }
        }
        .navigationTitle("Itinerary")
        .task {
            if viewModel.itinerary == nil {
                await viewModel.load()
            }
        }
        .task {
            await viewModel.listenForReplans()
        }
        .sheet(item: $viewModel.pendingProposal) { proposal in
            ReplanReviewView(
                proposal: proposal,
                isSubmitting: viewModel.isDeciding,
                onApprove: { await viewModel.approve(proposal) },
                onReject: { await viewModel.reject(proposal) }
            )
        }
        .alert("Couldn’t load itinerary", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }
}
