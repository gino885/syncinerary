import SwiftUI

struct SwipeView: View {
    let onPlanned: (UUID) -> Void

    @State private var viewModel: SwipeViewModel

    init(session: TripSession, onPlanned: @escaping (UUID) -> Void) {
        self.onPlanned = onPlanned
        _viewModel = State(initialValue: SwipeViewModel(session: session))
    }

    var body: some View {
        @Bindable var viewModel = viewModel

        Group {
            if viewModel.isLoading {
                ProgressView("Loading places…")
            } else if let candidate = viewModel.currentCandidate {
                VStack {
                    ProgressView(
                        value: Double(viewModel.currentIndex),
                        total: Double(max(viewModel.candidates.count, 1))
                    )
                    .accessibilityLabel("Swipe progress")
                    .accessibilityValue(viewModel.progressText)
                    .padding(.horizontal)

                    CandidateCardView(candidate: candidate)

                    SwipeControls(
                        isDisabled: viewModel.isSubmittingVote,
                        onDislike: dislike,
                        onLike: like
                    )
                    .padding()
                }
            } else if viewModel.isComplete {
                ContentUnavailableView {
                    Label("Voting complete", systemImage: "checkmark.circle")
                } description: {
                    Text("Build the itinerary from the group’s votes.")
                } actions: {
                    Button("Build itinerary", systemImage: "calendar.badge.clock", action: plan)
                        .buttonStyle(.borderedProminent)
                        .disabled(viewModel.isPlanning)
                }
            } else {
                ContentUnavailableView(
                    "No places found",
                    systemImage: "map",
                    description: Text("Try creating a supported destination again.")
                )
            }
        }
        .navigationTitle(viewModel.session.trip.destination)
        .task {
            await viewModel.load()
        }
        .sensoryFeedback(.selection, trigger: viewModel.currentIndex)
        .alert("Something went wrong", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }

    private func dislike() {
        Task { await viewModel.vote(.dislike) }
    }

    private func like() {
        Task { await viewModel.vote(.like) }
    }

    private func plan() {
        Task {
            if let tripID = await viewModel.plan() {
                onPlanned(tripID)
            }
        }
    }
}
