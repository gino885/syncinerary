import SwiftUI

/// A note pinned to a like, for the rest of the group to read.
struct VoteNoteSheet: View {
    let placeName: String
    let onSubmit: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var note = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(
                        "Only if the weather holds. I'd skip the queue.",
                        text: $note,
                        axis: .vertical
                    )
                    .lineLimit(3...6)
                } header: {
                    EyebrowText("What should the group know?")
                }
            }
            .journalPage()
            .navigationTitle(placeName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel", action: dismiss.callAsFunction)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Like with note", action: submit)
                        .disabled(note.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }

    private func submit() {
        let cleaned = note.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return }
        onSubmit(cleaned)
        dismiss()
    }
}
