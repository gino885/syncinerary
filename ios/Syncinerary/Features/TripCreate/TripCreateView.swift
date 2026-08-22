import SwiftUI

struct TripCreateView: View {
    let onCreated: (TripSession) -> Void

    @State private var viewModel = TripCreateViewModel()

    var body: some View {
        @Bindable var viewModel = viewModel

        Form {
            Section("Trip") {
                TextField("Destination", text: $viewModel.destination)
                    .textContentType(.addressCity)
                DatePicker(
                    "Start date",
                    selection: $viewModel.startDate,
                    displayedComponents: .date
                )
                DatePicker(
                    "End date",
                    selection: $viewModel.endDate,
                    in: viewModel.startDate...,
                    displayedComponents: .date
                )
            }

            Section("Traveler") {
                TextField("Your name", text: $viewModel.creatorName)
                    .textContentType(.name)
                TextField("Home city (optional)", text: $viewModel.creatorHomeCity)
                    .textContentType(.addressCity)
            }

            Section("Daily schedule") {
                DatePicker(
                    "Start exploring",
                    selection: $viewModel.dayStart,
                    displayedComponents: .hourAndMinute
                )
                DatePicker(
                    "Finish by",
                    selection: $viewModel.dayEnd,
                    displayedComponents: .hourAndMinute
                )
                Text("The default is 8:00 AM to 8:00 PM. You can adjust it for this trip.")
                    .foregroundStyle(.secondary)
            }

            Section {
                Button(action: createTrip) {
                    if viewModel.isSubmitting {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                    } else {
                        Label("Create trip", systemImage: "airplane.departure")
                            .frame(maxWidth: .infinity)
                    }
                }
                .disabled(!viewModel.canSubmit)
                .frame(minHeight: AppLayout.minimumTapHeight)
            }
        }
        .navigationTitle("Plan a trip")
        .onChange(of: viewModel.startDate) {
            viewModel.adjustEndDate()
        }
        .alert("Couldn’t create trip", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }

    private func createTrip() {
        Task {
            if let session = await viewModel.createTrip() {
                onCreated(session)
            }
        }
    }
}

#Preview {
    NavigationStack {
        TripCreateView(onCreated: { _ in })
    }
}
