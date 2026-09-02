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
                FunLoadingView(script: .stay)
            } else if viewModel.isPlanning {
                FunLoadingView(script: .plan(city: viewModel.session.trip.cities.first ?? viewModel.session.trip.destination))
            } else if viewModel.options.isEmpty {
                ContentUnavailableView(
                    "No stays found",
                    systemImage: "bed.double",
                    description: Text("Try another city.")
                )
            } else {
                List {
                    Section {
                        ForEach(viewModel.options) { option in
                            Button {
                                viewModel.choose(option)
                            } label: {
                                LodgingOptionRow(option: option, isSelected: viewModel.selectedID == option.id)
                            }
                            .buttonStyle(.plain)
                        }
                    } header: {
                        EyebrowText("Stay · \(TripDate.range(viewModel.options[0].tripStartDate, viewModel.options[0].tripEndDate))")
                    } footer: {
                        Text(viewModel.options[0].availabilityNote)
                            .font(.footnote)
                            .foregroundStyle(AppTheme.faded)
                    }
                    .journalRow()

                    Section {
                        Button("Choose and build the days", action: plan)
                            .buttonStyle(.stamp(ink: AppTheme.jade))
                            .disabled(viewModel.selectedID == nil || viewModel.isPlanning)
                            .listRowInsets(ListRowInsets.stamp)
                            .listRowSeparator(.hidden)
                    }
                    .journalRow()
                }
                .listStyle(.plain)
                .listRowSeparatorTint(AppTheme.rule)
                .animation(AppTheme.stampDown, value: viewModel.selectedID)
            }
        }
        .journalPage()
        .navigationTitle("Stay")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await viewModel.load()
        }
        .alert("Couldn't choose the stay", isPresented: $viewModel.isShowingError) { } message: {
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
