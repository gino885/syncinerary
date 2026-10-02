import SwiftUI

struct ItineraryView: View {
    @State private var viewModel: ItineraryViewModel
    @State private var selectedDay: Int?
    @State private var showingEditor = false
    @State private var addingPlace = false
    @State private var editingCandidateID: UUID?

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
                    if viewModel.liveUpdatesUnavailable || viewModel.pendingProposal != nil
                        || (selectedDay == nil && !(itinerary.narrative ?? "").isEmpty) {
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

                            if selectedDay == nil, let narrative = itinerary.narrative, !narrative.isEmpty {
                                ItineraryNarrativeCard(narrative: narrative)
                                    .listRowSeparator(.hidden)
                            }
                        }
                        .journalRow()
                    }

                    ForEach(itinerary.days.filter { selectedDay == nil || $0.day == selectedDay }) { day in
                        ItineraryDaySection(day: day, onAdd: {
                            selectedDay = day.day
                            openEditor(add: true)
                        }, onEdit: { stop in
                            selectedDay = day.day
                            openEditor(candidateID: stop.candidateID)
                        })
                    }

                    if selectedDay == nil {
                        WishlistSection(items: itinerary.wishlistNotPlaced)
                    }

                    if !itinerary.transitAttributions.isEmpty {
                        Section {
                            ForEach(itinerary.transitAttributions) { credit in
                                if let url = credit.url {
                                    Link(destination: url) {
                                        MetaLabel(verbatim: "\(credit.text) ↗", color: AppTheme.ink)
                                    }
                                } else {
                                    MetaLabel(verbatim: credit.text)
                                }
                            }
                        }
                        .journalRow()
                    }
                }
                .listStyle(.plain)
                .listRowSeparatorTint(AppTheme.rule)
                .id(selectedDay)
                .transition(.opacity)
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
        .animation(AppTheme.fade, value: selectedDay)
        // Keep the picker and its matched-geometry namespace outside the
        // changing list identity so the highlight can travel between days.
        .safeAreaInset(edge: .top, spacing: 0) {
            if let itinerary = viewModel.itinerary {
                ItineraryDayPicker(days: itinerary.days, selection: $selectedDay)
            }
        }
        .journalPage()
        .onChange(of: viewModel.itinerary?.days.map(\.day)) {
            if let selectedDay, viewModel.itinerary?.days.contains(where: { $0.day == selectedDay }) != true {
                self.selectedDay = nil
            }
        }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink { ChecklistView(session: viewModel.session) } label: {
                    Label("Checklist", systemImage: "checklist")
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button("Edit plan", systemImage: "square.and.pencil") { openEditor() }
                    .disabled(viewModel.itinerary == nil || viewModel.pendingProposal != nil || viewModel.isDeciding)
            }
        }
        .sheet(isPresented: $showingEditor, onDismiss: viewModel.finishEditing) {
            if let itinerary = viewModel.itinerary {
                ManualItineraryEditor(session: viewModel.session, itinerary: itinerary,
                    day: selectedDay ?? 0, addPlace: addingPlace, editCandidateID: editingCandidateID) { proposal in
                        viewModel.pendingProposal = proposal
                    }
            }
        }
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
    private func openEditor(add: Bool = false, candidateID: UUID? = nil) {
        guard viewModel.pendingProposal == nil, viewModel.itinerary != nil, !viewModel.isDeciding else {
            viewModel.showPendingReplan()
            return
        }
        addingPlace = add
        editingCandidateID = candidateID
        viewModel.isEditing = true
        showingEditor = true
    }

}
