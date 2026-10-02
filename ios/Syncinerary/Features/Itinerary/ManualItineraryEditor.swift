import SwiftUI

struct ManualItineraryEditor: View {
    @State private var viewModel: ManualItineraryViewModel
    @State private var editing: ItineraryDraftStop?
    @State private var showingPlaces: Bool
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    let onProposal: (ReplanProposalResponse) -> Void

    init(session: TripSession, itinerary: ItineraryResponse, day: Int = 0,
         addPlace: Bool = false, editCandidateID: UUID? = nil,
         onProposal: @escaping (ReplanProposalResponse) -> Void) {
        let model = ManualItineraryViewModel(session: session, itinerary: itinerary, day: day)
        _viewModel = State(initialValue: model)
        _showingPlaces = State(initialValue: addPlace)
        _editing = State(initialValue: model.stops.first { $0.candidateID == editCandidateID })
        self.onProposal = onProposal
    }

    var body: some View {
        @Bindable var model = viewModel
        NavigationStack {
            List {
                Section {
                    Picker("Day", selection: $model.selectedDay) {
                        ForEach(model.itinerary.days) { day in Text("Day \(day.day + 1)").tag(day.day) }
                    }
                }
                Section {
                    ForEach(model.dayStops) { stop in
                        Button { editing = stop } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(stop.timeRange)
                                    .font(AppType.mono).bold().foregroundStyle(AppTheme.accent)
                                    .contentTransition(reduceMotion ? .identity : .numericText())
                                Text(stop.name).font(.headline).foregroundStyle(AppTheme.ink)
                                if stop.fixed { Text("Fixed reservation").font(.caption) }
                            }
                            .frame(minHeight: 44, alignment: .leading)
                        }
                        .listRowBackground(AppTheme.surface)
                        .deleteDisabled(stop.fixed)
                        .moveDisabled(model.dayStops.contains(where: \.fixed))
                    }
                    .onDelete { offsets in
                        let dayStops = model.dayStops
                        for index in offsets { model.remove(dayStops[index]) }
                    }
                    .onMove(perform: model.move)
                    if model.dayStops.isEmpty { Text("Nothing scheduled").foregroundStyle(AppTheme.faded) }
                }
                Section {
                    Button("Add a place", systemImage: "plus") { showingPlaces = true }
                    Button("Adjust this day") { preview(adjustDay: true) }
                        .disabled(!model.valid)
                } footer: {
                    Text("Adjust this day keeps your places and finds times that fit.")
                }
                if let error = model.errorMessage {
                    Section { Text(error).foregroundStyle(AppTheme.stamp) }
                }
                if model.isSubmitting { ProgressView("Checking your changes") }
            }
            .journalPage()
            .animation(reduceMotion ? nil : AppTheme.selection, value: model.stops)
            .sensoryFeedback(.selection, trigger: model.stops)
            .safeAreaInset(edge: .bottom) {
                Button("Preview changes", systemImage: "arrow.right") { preview() }
                    .buttonStyle(JourneyButtonStyle())
                    .disabled(model.isSubmitting || !model.valid)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                    .background(AppTheme.canvas)
            }
            .environment(\.editMode, .constant(.active))
            .disabled(model.isSubmitting)
            .navigationTitle("Edit plan")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(model.isSubmitting) }
            }
            .interactiveDismissDisabled(model.isSubmitting)
            .sheet(item: $editing) { stop in
                ItineraryStopEditor(stop: stop, days: model.itinerary.days, isNew: false, onSave: model.update)
            }
            .sheet(isPresented: $showingPlaces) {
                ItineraryPlacePicker(viewModel: model) { stop in model.add(stop); showingPlaces = false }
            }
        }
    }

    private func preview(adjustDay: Bool = false) {
        Task {
            if let proposal = await viewModel.preview(adjustDay: adjustDay) {
                onProposal(proposal)
                dismiss()
            }
        }
    }
}
