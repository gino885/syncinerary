import SwiftUI

struct ShortlistView: View {
    let onConfirmed: (TripSession) -> Void

    @State private var viewModel: ShortlistViewModel

    init(session: TripSession, onConfirmed: @escaping (TripSession) -> Void) {
        self.onConfirmed = onConfirmed
        _viewModel = State(initialValue: ShortlistViewModel(session: session))
    }

    var body: some View {
        @Bindable var viewModel = viewModel

        Group {
            if viewModel.isLoading {
                ProgressView("Building the group shortlist…")
            } else if viewModel.candidates.isEmpty {
                ContentUnavailableView(
                    "No places to review",
                    systemImage: "list.star",
                    description: Text("Finish voting before building the shortlist.")
                )
            } else {
                List {
                    Section("Shortlist") {
                        ForEach(viewModel.selectedCandidates) { candidate in
                            ShortlistCandidateRow(
                                candidate: candidate,
                                isSelected: true,
                                isMustGo: viewModel.mustGoIDs.contains(candidate.id),
                                onToggleSelection: { viewModel.toggleSelection(candidate) },
                                onToggleMustGo: { viewModel.toggleMustGo(candidate) }
                            )
                        }
                    }

                    if !viewModel.wishlistCandidates.isEmpty {
                        Section("More ideas") {
                            ForEach(viewModel.wishlistCandidates) { candidate in
                                ShortlistCandidateRow(
                                    candidate: candidate,
                                    isSelected: false,
                                    isMustGo: false,
                                    onToggleSelection: { viewModel.toggleSelection(candidate) },
                                    onToggleMustGo: { }
                                )
                            }
                        }
                    }

                    Section {
                        Button("Confirm shortlist", systemImage: "checkmark.circle", action: confirm)
                            .buttonStyle(.borderedProminent)
                            .disabled(viewModel.selectedIDs.isEmpty || viewModel.isSubmitting)
                            .frame(minHeight: AppLayout.minimumTapHeight)

                        if let confirmation = viewModel.confirmation,
                           !confirmation.confirmedBy.isEmpty,
                           !confirmation.isConfirmed {
                            Button("Refresh confirmations", systemImage: "arrow.clockwise", action: refresh)
                            Text(viewModel.confirmationText)
                                .foregroundStyle(.secondary)
                        }
                    } footer: {
                        Text("Use the star for must-go places. At least half the group must confirm before planning.")
                    }
                }
            }
        }
        .navigationTitle("Choose the shortlist")
        .task {
            await viewModel.load()
        }
        .alert("Couldn’t update the shortlist", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }

    private func confirm() {
        Task {
            if await viewModel.saveAndConfirm() {
                onConfirmed(viewModel.session)
            }
        }
    }

    private func refresh() {
        Task {
            if await viewModel.refreshConfirmation() {
                onConfirmed(viewModel.session)
            }
        }
    }
}
