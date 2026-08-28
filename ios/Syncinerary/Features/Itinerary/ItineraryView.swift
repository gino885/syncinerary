import SwiftUI

struct ItineraryView: View {
    @State private var viewModel: ItineraryViewModel

    init(tripID: UUID) {
        _viewModel = State(initialValue: ItineraryViewModel(tripID: tripID))
    }

    var body: some View {
        @Bindable var viewModel = viewModel

        Group {
            if viewModel.isLoading && viewModel.itinerary == nil {
                ProgressView("Loading itinerary…")
            } else if let itinerary = viewModel.itinerary {
                List {
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
        .alert("Couldn’t load itinerary", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }
}
