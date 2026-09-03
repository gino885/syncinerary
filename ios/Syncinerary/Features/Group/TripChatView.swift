import SwiftUI

/// The trip thread. The only bottom-anchored screen in the app.
///
/// Its signature is the stamp on a link message: the group can see which of
/// the posts they shared the agent actually took, and which one still needs a
/// place name. Nothing else in the app closes that loop.
struct TripChatView: View {
    let trip: TripListRow

    @State private var messages: [TripMessage] = []
    @State private var draft = ""
    @State private var errorMessage: String?
    @FocusState private var composerFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: AppTheme.spacingL) {
                        ForEach(messages) { message in
                            MessageRow(message: message) { placeName in
                                Task { await name(message, as: placeName) }
                            }
                            .id(message.id)
                        }
                    }
                    .padding(AppTheme.spacingL)
                }
                .onChange(of: messages.count) { _, _ in
                    guard let last = messages.last else { return }
                    withAnimation(AppTheme.fade) {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }

            Rectangle()
                .fill(AppTheme.rule)
                .frame(height: AppTheme.hairlineWidth)

            composer
        }
        .background(AppTheme.paper)
        .navigationTitle(trip.destination)
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: AppTheme.spacingM) {
            TextField("Message the group", text: $draft, axis: .vertical)
                .font(AppType.body)
                .foregroundStyle(AppTheme.ink)
                .lineLimit(1...5)
                .focused($composerFocused)

            Button {
                Task { await send() }
            } label: {
                Image(systemName: "arrow.up")
                    .font(.system(.body, weight: .semibold))
            }
            .buttonStyle(.plain)
            .foregroundStyle(canSend ? AppTheme.ink : AppTheme.faded)
            .frame(minWidth: AppLayout.minimumTapHeight, minHeight: AppLayout.minimumTapHeight)
            .disabled(!canSend)
            .accessibilityLabel("Send message")
        }
        .padding(.horizontal, AppTheme.spacingL)
        .padding(.vertical, AppTheme.spacingS)
    }

    private var canSend: Bool {
        !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func load() async {
        do {
            messages = try await APIClient.shared.messages(tripID: trip.id)
            errorMessage = nil
        } catch {
            errorMessage = "Could not load the thread."
        }
    }

    /// Repair a link the app could not read. M7a-1 marks those
    /// needs_place_name, and the person who pasted it is the only one who can
    /// answer.
    private func name(_ message: TripMessage, as placeName: String) async {
        do {
            let updated = try await APIClient.shared.namePlace(
                tripID: trip.id,
                messageID: message.id,
                placeName: placeName
            )
            if let index = messages.firstIndex(where: { $0.id == updated.id }) {
                messages[index] = updated
            }
        } catch {
            errorMessage = "Could not add that place."
        }
    }

    private func send() async {
        let body = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else { return }
        draft = ""
        do {
            let posted = try await APIClient.shared.postMessage(
                tripID: trip.id,
                body: body
            )
            messages.append(posted)
        } catch {
            // Put the text back rather than losing what they typed.
            draft = body
            errorMessage = "Message not sent. Try again."
        }
    }
}
