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
                FunLoadingView(script: .shortlist)
            } else if viewModel.candidates.isEmpty {
                ContentUnavailableView(
                    "Nothing to shortlist yet",
                    systemImage: "list.bullet",
                    description: Text("Finish swiping first.")
                )
            } else {
                List {
                    Section {
                        ShortlistTallyLine(
                            goingCount: viewModel.selectedIDs.count,
                            mustGoCount: viewModel.mustGoIDs.count,
                            mustGoLimit: viewModel.session.trip.days,
                            confirmed: viewModel.confirmation?.confirmedBy.count ?? 0,
                            required: viewModel.confirmation?.confirmationsRequired ?? 0
                        )
                        .listRowSeparator(.hidden)
                    }
                    .journalRow()

                    Section {
                        ForEach(viewModel.selectedCandidates) { candidate in
                            ShortlistCandidateRow(
                                candidate: candidate,
                                isSelected: true,
                                isMustGo: viewModel.mustGoIDs.contains(candidate.id),
                                onToggleSelection: { viewModel.toggleSelection(candidate) },
                                onToggleMustGo: { viewModel.toggleMustGo(candidate) }
                            )
                        }
                    } header: {
                        EyebrowText("Going")
                    }
                    .journalRow()

                    if !viewModel.wishlistCandidates.isEmpty {
                        Section {
                            ForEach(viewModel.wishlistCandidates) { candidate in
                                ShortlistCandidateRow(
                                    candidate: candidate,
                                    isSelected: false,
                                    isMustGo: false,
                                    onToggleSelection: { viewModel.toggleSelection(candidate) },
                                    onToggleMustGo: { }
                                )
                            }
                        } header: {
                            EyebrowText("More ideas")
                        }
                        .journalRow()
                    }

                    Section {
                        Button("Confirm shortlist", action: confirm)
                            .buttonStyle(.stamp)
                            .disabled(viewModel.selectedIDs.isEmpty || viewModel.isSubmitting)
                            .listRowInsets(ListRowInsets.stamp)
                            .listRowSeparator(.hidden)

                        if let confirmation = viewModel.confirmation,
                           !confirmation.confirmedBy.isEmpty,
                           !confirmation.isConfirmed {
                            Button("Check for confirmations", action: refresh)
                                .foregroundStyle(AppTheme.ink)
                        }
                    } footer: {
                        Text("Half the group has to confirm before planning. Stars are must-go, up to \(viewModel.session.trip.days).")
                            .font(.footnote)
                            .foregroundStyle(AppTheme.faded)
                    }
                    .journalRow()
                }
                .listStyle(.plain)
                .listRowSeparatorTint(AppTheme.rule)
                .animation(AppTheme.settle, value: viewModel.selectedIDs)
            }
        }
        .journalPage()
        .navigationTitle("Shortlist")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await viewModel.load()
        }
        .alert("Couldn't update the shortlist", isPresented: $viewModel.isShowingError) { } message: {
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
