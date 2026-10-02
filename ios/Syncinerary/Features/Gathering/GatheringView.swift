import SwiftUI

/// The longest wait in the app, given words on a board.
struct GatheringView: View {
    let onGathered: (TripSession) -> Void

    @Environment(\.scenePhase) private var scenePhase
    @State private var viewModel: GatheringViewModel
    @State private var showingRoom = false

    init(session: TripSession, onGathered: @escaping (TripSession) -> Void) {
        self.onGathered = onGathered
        _viewModel = State(initialValue: GatheringViewModel(session: session))
    }

    var body: some View {
        Group {
            if let message = viewModel.errorMessage {
                ContentUnavailableView {
                    Label("Couldn't find places", systemImage: "wifi.exclamationmark")
                } description: {
                    Text(message)
                } actions: {
                    Button("Try again", action: retry)
                        .buttonStyle(.stamp)
                        .frame(maxWidth: 240)
                }
            } else {
                VStack(spacing: 16) {
                    ProgressView()
                    Text(viewModel.phaseLabel)
                    Text(viewModel.cityName).foregroundStyle(AppTheme.faded)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AppTheme.paper.ignoresSafeArea())
        .navigationTitle("Finding places")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            Button("Group room") { showingRoom = true }
        }
        .sheet(isPresented: $showingRoom) {
            NavigationStack {
                PreparationView(session: viewModel.session, onStarted: { _ in
                    showingRoom = false
                    retry()
                }, observeStartedRun: false)
                .toolbar { Button("Done") { showingRoom = false } }
            }
        }
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            await run()
        }
    }

    private func retry() {
        Task {
            await run()
        }
    }

    private func run() async {
        if await viewModel.gather() {
            onGathered(viewModel.session)
        }
    }
}
