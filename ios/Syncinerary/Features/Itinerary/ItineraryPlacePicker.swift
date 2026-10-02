import SwiftUI

struct ItineraryPlacePicker: View {
    @Bindable var viewModel: ManualItineraryViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var selected: ItineraryDraftStop?
    let onAdd: (ItineraryDraftStop) -> Void

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("Place or restaurant name", text: $viewModel.searchQuery,
                              prompt: Text("Place or restaurant name").foregroundStyle(AppTheme.faded))
                        .submitLabel(.search)
                        .onSubmit { Task { await viewModel.search() } }
                    Button("Search places", systemImage: "magnifyingglass") {
                        Task { await viewModel.search() }
                    }
                    Button("Saved places") { Task { await viewModel.search(savedOnly: true) } }
                }
                .disabled(viewModel.isSearching)
                Section("From a post") {
                    TextField("Instagram, TikTok or RedNote link", text: $viewModel.link,
                              prompt: Text("Instagram, TikTok or RedNote link").foregroundStyle(AppTheme.faded))
                        .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("Place name (optional)", text: $viewModel.linkedPlaceName,
                              prompt: Text("Place name (optional)").foregroundStyle(AppTheme.faded))
                    Button("Find the place in this post") { Task { await viewModel.readLink() } }
                        .disabled(viewModel.link.isEmpty || viewModel.isSearching)
                }
                if viewModel.isSearching { ProgressView("Finding places") }
                if let error = viewModel.errorMessage { Text(error).foregroundStyle(AppTheme.stamp) }
                Section("Places") {
                    if viewModel.availablePlaces.isEmpty && !viewModel.isSearching {
                        Text("Search for a place to add.").foregroundStyle(AppTheme.faded)
                    }
                    ForEach(viewModel.availablePlaces) { place in
                        Button {
                            Task { selected = await viewModel.select(place) }
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(place.name).font(.headline).foregroundStyle(AppTheme.ink)
                                if let city = place.city { Text(city).font(.subheadline).foregroundStyle(AppTheme.faded) }
                            }
                            .frame(minHeight: 44, alignment: .leading)
                        }
                        .disabled(viewModel.isSearching)
                    }
                }
            }
            .journalPage()
            .navigationTitle("Add a place")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } } }
            .task { await viewModel.search(savedOnly: true) }
            .sheet(item: $selected) { stop in
                ItineraryStopEditor(stop: stop, days: viewModel.itinerary.days, isNew: true) { stop in
                    onAdd(stop)
                    dismiss()
                }
            }
        }
    }
}
