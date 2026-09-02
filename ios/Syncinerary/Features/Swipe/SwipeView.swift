import SwiftUI

struct SwipeView: View {
    let onVotingComplete: (TripSession) -> Void

    @State private var viewModel: SwipeViewModel
    @State private var noteCandidate: CandidateCard?
    @State private var detailCandidate: CandidateCard?
    @State private var throwRequest: SwipeDecision?
    @State private var burst: [EmojiParticle] = []
    @State private var burstGeneration = 0
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
                        progressText: viewModel.progressText
                    )

                    ZStack {
                        SwipeDeckView(
                            cards: viewModel.upcoming,
                            photos: viewModel.photos,
                            throwRequest: $throwRequest,
                            onDecision: decide,
                            onDetails: showDetails
                        )
                        EmojiBurstView(particles: burst)
                    }
                    .frame(maxHeight: .infinity)

                    if viewModel.showsHint && !dynamicTypeSize.isAccessibilitySize {
                        SwipeHintView()
                    }

                    SwipeActionBar(
                        isDisabled: false,
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
                VotingCompleteView(onContinue: continueToShortlist)
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
        launchBurst(for: decision)
        AccessibilityNotification.Announcement(decision.announcement).post()
        Task {
            await viewModel.decide(decision)
        }
    }

    private func launchBurst(for decision: SwipeDecision) {
        burstGeneration += 1
        let generation = burstGeneration
        burst = EmojiParticle.burst(decision.burstEmojis)
        Task {
            try? await Task.sleep(for: .seconds(1.6))
            if generation == burstGeneration {
                burst = []
            }
        }
    }

    private func continueToShortlist() {
        onVotingComplete(viewModel.session)
    }
}
