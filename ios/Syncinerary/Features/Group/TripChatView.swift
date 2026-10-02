import SwiftUI

/// The trip thread. The only bottom-anchored screen in the app.
///
/// Its signature is the stamp on a link message: the group can see which of
/// the posts they shared the agent actually took, and which one still needs a
/// place name. Nothing else in the app closes that loop.
struct TripChatView: View {
    let trip: TripListRow

    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var model: TripChatViewModel
    @FocusState private var composerFocused: Bool

    init(trip: TripListRow) {
        self.trip = trip
        _model = State(initialValue: TripChatViewModel(trip: trip))
    }

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: AppTheme.spacingL) {
                        ForEach(model.messages) { message in
                            MessageRow(message: message) { placeName in
                                Task { await model.name(message, as: placeName) }
                            }
                            .id(message.id)
                        }
                    }
                    .padding(AppTheme.spacingL)
                }
                .onChange(of: model.messages.count) { _, _ in
                    guard let last = model.messages.last else { return }
                    withAnimation(reduceMotion ? nil : AppTheme.fade) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }

            Rectangle()
                .fill(AppTheme.rule)
                .frame(height: AppTheme.hairlineWidth)

            if let error = model.errorMessage {
                HStack {
                    Text(error).font(.footnote).foregroundStyle(AppTheme.stamp)
                    Spacer(minLength: 0)
                    Button("Dismiss", systemImage: "xmark") { model.dismissError() }
                        .labelStyle(.iconOnly)
                        .frame(minWidth: 44, minHeight: 44)
                }
                .padding(.horizontal, AppTheme.spacingL)
            }
            composer
        }
        .background(AppTheme.paper)
        .navigationTitle(trip.destination)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    if let session = model.session {
                        NavigationLink("Group settings", value: AppRoute.preparation(session))
                    } else {
                        Button("Load group settings") { Task { await model.load() } }
                    }
                    NavigationLink("Saved links") { GroupSavedLinksView(tripID: trip.id) }
                } label: {
                    Image(systemName: "ellipsis")
                        .frame(minWidth: 44, minHeight: 44)
                }
                .accessibilityLabel("Group options")
            }
        }
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            while !Task.isCancelled {
                await model.load()
                do { try await Task.sleep(for: .seconds(5)) } catch { return }
            }
        }
        .refreshable { await model.load() }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: AppTheme.spacingM) {
            TextField("Message the group", text: $model.draft, axis: .vertical)
                .font(AppType.body)
                .foregroundStyle(AppTheme.ink)
                .lineLimit(1...5)
                .focused($composerFocused)

            Button {
                Task { await model.send() }
            } label: {
                Image(systemName: "arrow.up")
                    .font(.system(.body, weight: .semibold))
                    .frame(minWidth: AppLayout.minimumTapHeight, minHeight: AppLayout.minimumTapHeight)
            }
            .buttonStyle(.plain)
            .foregroundStyle(model.canSend ? AppTheme.ink : AppTheme.faded)
            .disabled(!model.canSend)
            .accessibilityLabel("Send message")
        }
        .padding(.horizontal, AppTheme.spacingL)
        .padding(.vertical, AppTheme.spacingS)
    }
}
