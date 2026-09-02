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
                FunLoadingView(script: .itinerary)
            } else if let itinerary = viewModel.itinerary {
                List {
                    Section {
                        if viewModel.liveUpdatesUnavailable {
                            MetaLabel("Live updates reconnecting")
                        }

                        if viewModel.pendingProposal != nil {
                            Button("Review the trip update", action: viewModel.showPendingReplan)
                                .buttonStyle(.stamp)
                                .listRowInsets(ListRowInsets.stamp)
                                .listRowSeparator(.hidden)
                        }

                        if let narrative = itinerary.narrative, !narrative.isEmpty {
                            ItineraryNarrativeCard(narrative: narrative)
                                .listRowSeparator(.hidden)
                        }
                    }
                    .journalRow()

                    ForEach(itinerary.days) { day in
                        ItineraryDaySection(day: day)
                    }

                    WishlistSection(items: itinerary.wishlistNotPlaced)

                    if itinerary.usesTransitous,
                       let sourcesURL = URL(string: "https://transitous.org/sources/") {
                        Section {
                            Link(destination: sourcesURL) {
                                MetaLabel("Transit data by Transitous ↗", color: AppTheme.ink)
                            }
                        }
                        .journalRow()
                    }
                }
                .listStyle(.plain)
                .listRowSeparatorTint(AppTheme.rule)
                .refreshable {
                    await viewModel.load()
                }
            } else {
                ContentUnavailableView(
                    "No itinerary",
                    systemImage: "calendar",
                    description: Text("Pull to try again.")
                )
            }
        }
        .journalPage()
        .navigationTitle(viewModel.session.trip.destination)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if viewModel.itinerary == nil {
                await viewModel.load()
            }
        }
        .task {
            await viewModel.listenForReplans()
        }
        .sheet(isPresented: $viewModel.isShowingReplan) {
            if let proposal = viewModel.pendingProposal {
                ReplanReviewView(
                    proposal: proposal,
                    isSubmitting: viewModel.isDeciding,
                    onApprove: { await viewModel.approve(proposal) },
                    onReject: { await viewModel.reject(proposal) }
                )
            }
        }
        .alert("Couldn't load the itinerary", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }
}
