import SwiftUI

struct ChecklistItemEditor: View {
    let model: ChecklistViewModel
    let item: ChecklistItem?
    @Environment(\.dismiss) private var dismiss
    @State private var title: String
    @State private var notes: String
    @State private var completed: Bool
    @State private var confirmDelete = false

    init(model: ChecklistViewModel, item: ChecklistItem?) {
        self.model = model
        self.item = item
        _title = State(initialValue: item?.title ?? "")
        _notes = State(initialValue: item?.notes ?? "")
        _completed = State(initialValue: item?.completed ?? false)
    }

    var body: some View {
        NavigationStack {
            Form {
                TextField("Task", text: $title, axis: .vertical)
                TextField("Notes (optional)", text: $notes, axis: .vertical)
                Toggle("Completed", isOn: $completed)
                if let error = model.errorMessage { Text(error).foregroundStyle(.red) }
                if item != nil {
                    Button("Delete task", role: .destructive) { confirmDelete = true }
                }
            }
            .disabled(model.isBusy)
            .journalPage()
            .navigationTitle(item == nil ? "Add task" : "Edit task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        Task { if await model.save(item, title: title, notes: notes, completed: completed) { dismiss() } }
                    }
                    .disabled(model.isBusy || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || title.count > 200 || notes.count > 1000)
                }
            }
            .confirmationDialog("Delete this task?", isPresented: $confirmDelete, titleVisibility: .visible) {
                Button("Delete task", role: .destructive) {
                    Task { if let item, await model.remove(item) { dismiss() } }
                }
            }
        }
        .interactiveDismissDisabled(model.isBusy)
        .onAppear { model.errorMessage = nil }
    }
}
