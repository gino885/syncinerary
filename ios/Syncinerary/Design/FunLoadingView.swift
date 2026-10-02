import SwiftUI

/// Current work in large rounded type, with previous loading lines above it. The
/// owning screen keeps its alert, so a failure is never hidden behind a
/// friendly sentence.
struct FunLoadingView: View {
    let script: LoadingScript

    @State private var lineIndex = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// At most two finished lines stay on the page; more turns into noise.
    private var previousLines: [LoadingLine] {
        guard lineIndex > 0 else { return [] }
        return Array(script.lines[max(0, lineIndex - 2)..<lineIndex])
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingL) {
            EyebrowText(verbatim: String(localized: script.title))

            VStack(alignment: .leading, spacing: AppTheme.spacingM) {
                ForEach(previousLines, id: \.self) { line in
                    Label(line.text, systemImage: line.symbolName)
                        .font(AppType.body)
                        .foregroundStyle(AppTheme.faded)
                        .strikethrough(color: AppTheme.rule)
                }

                Label(
                    script.lines[lineIndex].text,
                    systemImage: script.lines[lineIndex].symbolName
                )
                    .font(AppType.name)
                    .foregroundStyle(AppTheme.ink)
                    .id(lineIndex)
                    .transition(
                        reduceMotion
                            ? .opacity
                            : .asymmetric(
                                insertion: .offset(y: AppTheme.textTravel).combined(with: .opacity),
                                removal: .offset(y: -AppTheme.textTravel).combined(with: .opacity)
                            )
                    )
            }

            ProgressView()
                .tint(AppTheme.stamp)
                .padding(.top, AppTheme.spacingS)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(AppTheme.spacingXL)
        .padding(.top, 40)
        .background(AppTheme.paper)
        .clipped()
        .task(id: script) {
            await cycleLines()
        }
        .accessibilityElement(children: .combine)
    }

    private func cycleLines() async {
        lineIndex = 0
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(2.4))
            guard !Task.isCancelled else { return }
            withAnimation(reduceMotion ? nil : AppTheme.textSwap) {
                lineIndex = (lineIndex + 1) % script.lines.count
            }
        }
    }
}

#Preview {
    FunLoadingView(script: .gathering(city: "Sapporo"))
}
