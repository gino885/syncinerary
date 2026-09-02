import SwiftUI

struct SavedPostsView: View {
    let onContinue: (TripSession) -> Void

    @State private var viewModel: SavedPostsViewModel

    init(session: TripSession, onContinue: @escaping (TripSession) -> Void) {
        self.onContinue = onContinue
        _viewModel = State(initialValue: SavedPostsViewModel(session: session))
    }

    var body: some View {
        @Bindable var viewModel = viewModel

        Form {
            FriendsPlanningHeader()
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())

            Section {
                TextField("Instagram, TikTok, or RedNote link", text: $viewModel.postURL)
                    .textContentType(.URL)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()

                TextField("Place name, if the link doesn't say", text: $viewModel.placeName)
                    .textContentType(.location)

                Button("Add post", action: attach)
                    .disabled(!viewModel.canAttach)
                    .frame(minHeight: AppLayout.minimumTapHeight)
            }

            if !viewModel.attachments.isEmpty {
                Section {
                    ForEach(viewModel.attachments) { attachment in
                        AttachedPostRow(attachment: attachment)
                    }
                } header: {
                    EyebrowText("Added")
                }
            }

            Section {
                Button("Start swiping", action: continueToSwipe)
                    .buttonStyle(.stamp)
                    .listRowBackground(Color.clear)
                    .listRowInsets(ListRowInsets.stamp)
            } footer: {
                Text("Optional. The places already gathered are waiting either way.")
            }
        }
        .journalPage()
        .navigationTitle(viewModel.session.trip.destination)
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(true)
        .alert("Couldn't add this post", isPresented: $viewModel.isShowingError) { } message: {
            Text(viewModel.errorMessage)
        }
    }

    private func attach() {
        Task { await viewModel.attach() }
    }

    private func continueToSwipe() {
        onContinue(viewModel.session)
    }
}

#Preview {
    NavigationStack {
        SavedPostsView(
            session: TripSession(
                trip: TripSummary(id: UUID(), destination: "Sapporo, Otaru", cities: ["Sapporo", "Otaru"], country: "Japan", timezone: "Asia/Tokyo", startDate: "2026-09-25", endDate: "2026-09-29", days: 5, status: "setup"),
                travelerID: UUID(),
                planRequest: .standard
            ),
            onContinue: { _ in }
        )
    }
}
