import SwiftUI

struct SwipeView: View {
    let onVotingComplete: (TripSession) -> Void

    @State private var viewModel: SwipeViewModel
    @State private var noteCandidate: CandidateCard?
    @State private var detailCandidate: CandidateCard?
    @State private var throwRequest: SwipeDecision?
    @State private var reaction: SwipeDecision?
    @State private var reactionGeneration = 0
    @State private var isDeckAnimating = false
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(session: TripSession, onVotingComplete: @escaping (TripSession) -> Void) {
        self.onVotingComplete = onVotingComplete
        _viewModel = State(initialValue: SwipeViewModel(session: session))
    }

    var body: some View {
        @Bindable var viewModel = viewModel

        Group {
            if viewModel.isLoading {
                FunLoadingView(script: .deck)
            } else if !viewModel.upcoming.isEmpty {
                VStack(spacing: AppTheme.spacingM) {
                    SwipeProgressHeader(
                        current: viewModel.currentIndex,
                        total: viewModel.candidates.count,
                        progressText: viewModel.progressText,
                        canGoBack: viewModel.canGoBack && !isDeckAnimating,
                        onPrevious: showPrevious
                    )

                    ZStack {
                        SwipeDeckView(
                            cards: viewModel.upcoming,
                            photos: viewModel.photos,
                            throwRequest: $throwRequest,
                            isThrowing: $isDeckAnimating,
                            onDecision: decide,
                            onDetails: showDetails
                        )
                        if let reaction {
                            DecisionCharmView(decision: reaction)
                                .id(reactionGeneration)
                                .padding(AppTheme.spacingM)
                                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomTrailing)
                        }
                    }
                    .frame(maxHeight: .infinity)

                    if viewModel.showsHint && !dynamicTypeSize.isAccessibilitySize {
                        SwipeHintView()
                    }

                    SwipeActionBar(
                        isDisabled: isDeckAnimating,
                        onDislike: dislike,
                        onLikeWithNote: showNote,
                        onLike: like,
                        onMustHave: mustHave
                    )
                    .padding(.bottom, AppTheme.spacingS)
                }
                .padding(.horizontal, AppTheme.spacingL)
                .animation(AppTheme.fade, value: viewModel.showsHint)
            } else if viewModel.isComplete {
                VotingCompleteView(
                    onContinue: continueToShortlist,
                    onReviewLast: showPrevious
                )
            } else {
                ContentUnavailableView(
                    "No places yet",
                    systemImage: "map",
                    description: Text("Start a new trip to gather some.")
                )
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .journalPage()
        .navigationTitle(viewModel.session.trip.destination)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await viewModel.load()
        }
        .sensoryFeedback(trigger: viewModel.decisionCount) { _, _ in
            viewModel.lastDecision == .mustHave ? .success : .impact(weight: .medium)
        }
        .sheet(item: $noteCandidate) { candidate in
            VoteNoteSheet(placeName: candidate.nameCanonical, onSubmit: likeWithNote)
        }
        .sheet(item: $detailCandidate) { candidate in
            CandidateDetailView(candidate: candidate, photo: viewModel.photos[candidate.id])
        }
        .alert("Something went wrong", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }

    // MARK: Buttons ask the deck to throw the card

    private func dislike() {
        throwRequest = .dislike
    }

    private func like() {
        throwRequest = .like
    }

    private func mustHave() {
        throwRequest = .mustHave
    }

    private func likeWithNote(_ note: String) {
        throwRequest = .likeWithNote(note)
    }

    private func showNote() {
        noteCandidate = viewModel.currentCandidate
    }

    private func showDetails(_ candidate: CandidateCard) {
        detailCandidate = candidate
    }

    // MARK: The deck reports a decision once the card has left

    private func decide(_ decision: SwipeDecision) {
        launchReaction(for: decision)
        AccessibilityNotification.Announcement(decision.announcement).post()
        Task {
            await viewModel.decide(decision)
        }
    }

    private func launchReaction(for decision: SwipeDecision) {
        reactionGeneration += 1
        let generation = reactionGeneration
        reaction = decision
        Task {
            try? await Task.sleep(for: .milliseconds(720))
            if generation == reactionGeneration {
                reaction = nil
            }
        }
    }

    private func showPrevious() {
        withAnimation(AppTheme.settle) {
            viewModel.showPrevious()
        }
        AccessibilityNotification.Announcement("Showing previous card").post()
    }

    private func continueToShortlist() {
        onVotingComplete(viewModel.session)
    }
}
