import SwiftUI

struct SwipeView: View {
    let onVotingComplete: (TripSession) -> Void

    @State private var viewModel: SwipeViewModel
    @State private var noteCandidate: CandidateCard?

    init(session: TripSession, onVotingComplete: @escaping (TripSession) -> Void) {
        self.onVotingComplete = onVotingComplete
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

                    CandidateCardView(
                        candidate: candidate,
                        photo: viewModel.currentPhoto
                    )

                    SwipeControls(
                        isDisabled: viewModel.isSubmittingVote,
                        onDislike: dislike,
                        onLike: like,
                        onLikeWithNote: showNote,
                        onMustHave: mustHave
                    )
                    .padding()
                }
            } else if viewModel.isComplete {
                ContentUnavailableView {
                    Label("Voting complete", systemImage: "checkmark.circle")
                } description: {
                    Text("Build the itinerary from the group’s votes.")
                } actions: {
                    Button("Review shortlist", systemImage: "list.star", action: continueToShortlist)
                        .buttonStyle(.borderedProminent)
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
        .sheet(item: $noteCandidate) { candidate in
            VoteNoteSheet(placeName: candidate.nameCanonical, onSubmit: likeWithNote)
        }
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

    private func showNote() {
        noteCandidate = viewModel.currentCandidate
    }

    private func likeWithNote(_ note: String) {
        Task { await viewModel.vote(.likeWithNote, noteText: note) }
    }

    private func mustHave() {
        Task { await viewModel.vote(.mustHave) }
    }

    private func continueToShortlist() {
        onVotingComplete(viewModel.session)
    }
}
