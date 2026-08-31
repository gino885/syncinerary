import SwiftUI

struct LodgingView: View {
    let onPlanned: (TripSession) -> Void

    @State private var viewModel: LodgingViewModel

    init(session: TripSession, onPlanned: @escaping (TripSession) -> Void) {
        self.onPlanned = onPlanned
        _viewModel = State(initialValue: LodgingViewModel(session: session))
    }

    var body: some View {
        @Bindable var viewModel = viewModel

        Group {
            if viewModel.isLoading {
                ProgressView("Comparing places to stay…")
            } else if viewModel.options.isEmpty {
                ContentUnavailableView(
                    "No lodging found",
                    systemImage: "bed.double",
                    description: Text("Try creating the trip again or choose another city.")
                )
            } else {
                List {
                    Section {
                        ForEach(viewModel.options) { option in
                            Button {
                                viewModel.choose(option)
                            } label: {
                                LodgingOptionRow(
                                    option: option,
                                    isSelected: viewModel.selectedID == option.id
                                )
                            }
                            .buttonStyle(.plain)
                        }
                    } header: {
                        Text("Top places near your trip")
                    } footer: {
                        Text(viewModel.options[0].availabilityNote)
                    }

                    Section {
                        Button("Choose stay and build itinerary", systemImage: "calendar.badge.clock", action: plan)
                            .disabled(viewModel.selectedID == nil || viewModel.isPlanning)
                            .frame(minHeight: AppLayout.minimumTapHeight)
                    }
                }
            }
        }
        .navigationTitle("Choose a stay")
        .task {
            await viewModel.load()
        }
        .alert("Couldn’t choose lodging", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }

    private func plan() {
        Task {
            if await viewModel.selectAndPlan() {
                onPlanned(viewModel.session)
            }
        }
    }
}
