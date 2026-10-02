import SwiftUI

struct ChecklistView: View {
    @State private var model: ChecklistViewModel
    @State private var editing: ChecklistItem?
    @State private var showingEditor = false

    init(session: TripSession) {
        _model = State(initialValue: ChecklistViewModel(session: session))
    }

    var body: some View {
        List {
            Section {
                Text("\(model.items.filter(\.completed).count) of \(model.items.count) done")
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(AppTheme.faded)
                ForEach(model.items) { item in
                    HStack(alignment: .top, spacing: 8) {
                        Button { Task { await model.toggle(item) } } label: {
                            Image(systemName: item.completed ? "checkmark.circle.fill" : "circle")
                                .font(.title2)
                                .foregroundStyle(item.completed ? AppTheme.accent : AppTheme.faded)
                                .frame(minWidth: 44, minHeight: 44)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(item.completed ? String(localized: "Mark incomplete") : String(localized: "Mark complete"))
                        .accessibilityValue(item.title)
                        Button {
                            editing = item
                            showingEditor = true
                        } label: {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(item.title)
                                    .strikethrough(item.completed)
                                    .foregroundStyle(item.completed ? AppTheme.faded : AppTheme.ink)
                                if !item.notes.isEmpty {
                                    Text(item.notes).font(.footnote).foregroundStyle(AppTheme.faded)
                                }
                            }
                            .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                        .accessibilityHint("Edit task")
                    }
                }
                if model.items.isEmpty && !model.isBusy {
                    Text("Add what you need to get ready.").foregroundStyle(AppTheme.faded)
                }
            } footer: {
                Text("Shared with your trip. Suggested tasks are reminders, not confirmed bookings.")
            }
            if let error = model.errorMessage {
                Section {
                    Text(error).foregroundStyle(.red)
                    Button("Refresh checklist") { Task { await model.load() } }
                }
            }
        }
        .disabled(model.isBusy)
        .overlay { if model.isBusy && model.items.isEmpty { ProgressView() } }
        .journalPage()
        .navigationTitle("Checklist")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            Button("Add task", systemImage: "plus") { editing = nil; showingEditor = true }
                .disabled(model.isBusy)
        }
        .refreshable { await model.load() }
        .task { await model.load() }
        .sheet(isPresented: $showingEditor) {
            ChecklistItemEditor(model: model, item: editing)
        }
    }
}
