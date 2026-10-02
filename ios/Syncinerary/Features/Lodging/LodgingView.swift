import SwiftUI

struct LodgingView: View {
    let onPlanned: (TripSession) -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
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
            } else {
                List {
                    BookedHotelForm(model: viewModel)

                    Section {
                        ForEach(viewModel.options) { option in
                            Button {
                                viewModel.choose(option)
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    LodgingOptionRow(option: option, isSelected: viewModel.selectedID == option.id)
                                    if option.isBooked == true {
                                        Text("Already booked").font(.caption.weight(.semibold)).foregroundStyle(AppTheme.accent)
                                    }
                                }
                            }
                            .buttonStyle(.plain)
                            .disabled(viewModel.isSavingHotel)
                        }
                    } header: {
                        EyebrowText("Stay · \(TripDate.range(viewModel.session.trip.startDate, viewModel.session.trip.endDate))")
                    } footer: {
                        Text(viewModel.options.first(where: { $0.id == viewModel.selectedID })?.isBooked == true
                             ? String(localized: "Saved as booked. Reservation details aren't verified.")
                             : String(localized: "Room availability is not verified. Confirm dates with the hotel before booking."))
                            .font(.footnote)
                            .foregroundStyle(AppTheme.faded)
                    }
                    .journalRow()

                    Section {
                        Button("Choose and build the days", action: plan)
                            .buttonStyle(.stamp(ink: AppTheme.jade))
                            .disabled(viewModel.selectedID == nil || viewModel.isPlanning || viewModel.isSavingHotel || viewModel.isSearchingHotel)
                            .listRowInsets(ListRowInsets.stamp)
                            .listRowSeparator(.hidden)
                    }
                    .journalRow()
                }
                .listStyle(.plain)
                .listRowSeparatorTint(AppTheme.rule)
                .animation(reduceMotion ? nil : AppTheme.stampDown, value: viewModel.selectedID)
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
