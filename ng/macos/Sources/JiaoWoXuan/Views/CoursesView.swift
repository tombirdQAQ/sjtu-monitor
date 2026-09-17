import JiaoWoXuanCore
import SwiftUI

struct CoursesView: View {
    @Environment(AppStore.self) private var store
    @State private var showInspector = true

    var body: some View {
        @Bindable var store = store
        // 不用 VSplitView:它在 NavigationSplitView + inspector 里会触发 AppKit 约束更新死循环并崩溃。
        VStack(spacing: 0) {
            TermBar()
            CourseTable()
                .frame(maxHeight: .infinity)
            PlanEditor()
                .frame(height: 320)
                .glassCard(cornerRadius: 24)
                .padding(.horizontal, 12)
                .padding(.bottom, 12)
                .padding(.top, 6)
        }
        .background { AmbientBackground() }
        .searchable(text: $store.courseFilter.query, placement: .toolbar, prompt: "搜索课程、教师、编号、时间或地点")
        .toolbar {
            ToolbarItemGroup(placement: .automatic) {
                CourseFilterMenu()
                Menu {
                    Button("获取全量课程") { store.run("bootstrap") }
                        .disabled(store.running.contains("bootstrap"))
                    Button("获取全部评价") { store.run("ratings-all") }
                        .disabled(store.running.contains("ratings-all"))
                    Divider()
                    Button("读取教务当前学期") { store.run("detect-term") }
                        .disabled(store.running.contains("detect-term"))
                } label: {
                    Label("同步", systemImage: "arrow.down.circle")
                }
                .help("从教务网站同步课程目录与评价")
            }
            ToolbarItem(placement: .automatic) {
                Button {
                    showInspector.toggle()
                } label: {
                    Label("课程详情", systemImage: "sidebar.trailing")
                }
                .help("显示或隐藏课程详情")
            }
        }
        .inspector(isPresented: $showInspector) {
            CourseInspector(course: store.inspectedCourse.flatMap { store.coursesById[$0] })
                .inspectorColumnWidth(min: 260, ideal: 300, max: 420)
        }
        .onChange(of: store.courseSelection) { _, selection in
            if let last = selection.first, selection.count == 1 {
                store.inspectedCourse = last
            } else if let current = store.inspectedCourse, !selection.contains(current), let any = selection.first {
                store.inspectedCourse = any
            }
        }
    }
}

private struct TermBar: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        if let snapshot = store.snapshot {
            let active = snapshot.terms.first(where: \.active)
            let history = snapshot.terms.filter { !$0.active }
            HStack(spacing: 10) {
                Text(active?.label ?? snapshot.user.term).font(.headline)
                if let site = snapshot.siteTerm, site.key != nil {
                    StatusBadge(text: site.matchesActive ? "教务当前" : "与教务当前不一致", tone: site.matchesActive ? .success : .danger)
                }
                Text(siteText(snapshot.siteTerm))
                    .font(.callout)
                    .foregroundStyle(snapshot.siteTerm.map { $0.matchesActive || $0.key == nil } ?? true ? AnyShapeStyle(.secondary) : AnyShapeStyle(Color.red))
                    .lineLimit(1)
                if let site = snapshot.siteTerm, let key = site.key, !site.matchesActive {
                    Button("切换到教务当前学期") {
                        let parts = key.split(separator: "-").map(String.init)
                        guard parts.count == 2 else { return }
                        if store.groupsDirty {
                            store.notice = Notice(title: "请先保存方案", message: "当前学期的方案还有未保存的修改，切换学期前请先保存或放弃修改。")
                            return
                        }
                        Task { await store.switchTerm(xkxnm: parts[0], xkxqm: parts[1]) }
                    }
                    .controlSize(.small)
                    .disabled(store.busy)
                }
                Spacer()
                if !history.isEmpty {
                    Menu {
                        ForEach(history) { term in
                            Text(term.label + (term.groupCount > 0 ? " · \(term.groupCount) 个方案" : ""))
                        }
                    } label: {
                        Text("历史学期 \(history.count)")
                    }
                    .menuStyle(.borderlessButton)
                    .fixedSize()
                    .help("历史学期仅供参考；只有教务网站当前学期能抓到数据")
                }
                Text("\(store.filteredCourses.count) / \(snapshot.courses.count)")
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
        }
    }

    private func siteText(_ site: SiteTermInfo?) -> String {
        guard let site else { return "教务当前学期将在获取全量课程时读取" }
        guard site.key != nil else { return "教务网站当前未开放选课" }
        var text = "自主选课\(site.zzxkOpen ? "开放" : "未开放") · 补退选\(site.tjxkbkkOpen ? "开放" : "未开放")"
        if let at = site.detectedAt { text += " · \(at)" }
        return text
    }
}

private struct CourseFilterMenu: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        @Bindable var store = store
        let active = store.courseFilter.category != CourseFilter.allCategories
            || store.courseFilter.onlyOpen || store.courseFilter.onlyUnassigned
        Menu {
            Picker("类别", selection: $store.courseFilter.category) {
                Text("全部类别").tag(CourseFilter.allCategories)
                ForEach(store.snapshot?.categories ?? [], id: \.self) { Text($0).tag($0) }
            }
            Picker("排序", selection: $store.courseFilter.sort) {
                ForEach(CourseSort.allCases) { Text($0.label).tag($0) }
            }
            Divider()
            Toggle("只看有空位", isOn: $store.courseFilter.onlyOpen)
            Toggle("只看未分配", isOn: $store.courseFilter.onlyUnassigned)
            if active {
                Divider()
                Button("清除筛选") {
                    store.courseFilter.category = CourseFilter.allCategories
                    store.courseFilter.onlyOpen = false
                    store.courseFilter.onlyUnassigned = false
                }
            }
        } label: {
            Label("筛选", systemImage: active ? "line.3.horizontal.decrease.circle.fill" : "line.3.horizontal.decrease.circle")
        }
        .help("筛选与排序")
    }
}

private struct CourseTable: View {
    @Environment(AppStore.self) private var store

    var body: some View {
        @Bindable var store = store
        let rows = store.filteredCourses
        Table(rows, selection: $store.courseSelection) {
            TableColumn("课程") { course in
                VStack(alignment: .leading, spacing: 1) {
                    Text(course.title).lineLimit(1)
                    Text(course.className).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            .width(min: 180, ideal: 260)
            TableColumn("教师") { Text($0.teachers).lineLimit(1) }
                .width(min: 60, ideal: 110)
            TableColumn("时间") { Text($0.firstSchedule).lineLimit(1).help($0.schedule.joined(separator: "\n")) }
                .width(min: 120, ideal: 200)
            TableColumn("课程号") { Text($0.kch ?? "-").font(.body.monospaced()).lineLimit(1) }
                .width(min: 70, ideal: 90)
            TableColumn("容量") { Text($0.seatText).monospacedDigit() }
                .width(min: 50, ideal: 70)
            TableColumn("状态") { StatusBadge(text: $0.statusText, tone: $0.statusTone) }
                .width(min: 50, ideal: 64)
            TableColumn("评分") { course in
                Text(course.ratingText)
                    .foregroundStyle(course.rating.status == .rated ? .primary : .secondary)
                    .lineLimit(1)
            }
            .width(min: 60, ideal: 100)
            TableColumn("方案") { Text($0.group ?? "").foregroundStyle(.secondary).lineLimit(1) }
                .width(min: 50, ideal: 80)
        }
        .tableStyle(.inset(alternatesRowBackgrounds: true))
        .scrollContentBackground(.hidden)
        .contextMenu(forSelectionType: String.self) { ids in
            let groupName = store.selectedGroup ?? "当前方案"
            Button("加入“\(groupName)”") { add(ids) }
                .disabled(ids.isEmpty || store.selectedGroup == nil)
            Divider()
            Button("拷贝课程号") { copy(ids.compactMap { store.coursesById[$0]?.kch }) }
            Button("拷贝教学班 ID") { copy(Array(ids)) }
        } primaryAction: { ids in
            add(ids)
        }
        .overlay {
            if rows.isEmpty {
                EmptyHint(title: "没有符合条件的课程", symbol: "magnifyingglass",
                          message: store.courses.isEmpty ? "请先从工具栏“同步”获取全量课程" : nil)
            }
        }
    }

    private func add(_ ids: Set<String>) {
        let ordered = store.filteredCourses.map(\.jxbId).filter(ids.contains)
        Task {
            if let warning = await store.addCourses(ordered) {
                store.notice = Notice(title: "时间冲突提示", message: warning)
            }
        }
    }

    private func copy(_ values: [String]) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(values.joined(separator: "\n"), forType: .string)
    }
}

private struct CourseInspector: View {
    let course: CourseRow?

    var body: some View {
        if let course {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(course.category).font(.caption).foregroundStyle(.secondary)
                        Text(course.title).font(.title3.weight(.semibold)).textSelection(.enabled)
                        HStack {
                            Text(course.className).foregroundStyle(.secondary)
                            Spacer()
                            StatusBadge(text: course.chosen ? "当前已选" : course.availabilityText, tone: course.statusTone)
                        }
                    }
                }
                Section(course.rating.status.label) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(course.rating.scoreText)
                            .font(.system(size: 34, weight: .semibold, design: .rounded))
                            .foregroundStyle(course.rating.status == .rated ? .primary : .secondary)
                        Spacer()
                        VStack(alignment: .trailing) {
                            Text("\(course.rating.count.map(String.init) ?? "-") 条评价")
                            Text(course.rating.semester ?? "").foregroundStyle(.secondary)
                        }
                        .font(.callout)
                    }
                    LabeledContent("教师", value: course.rating.teacher ?? course.teachers)
                    if let message = course.rating.message {
                        Text(message).font(.callout).foregroundStyle(.secondary)
                    }
                }
                Section("授课信息") {
                    LabeledContent("教师", value: course.teachers)
                    LabeledContent("时间") { Text(course.schedule.joined(separator: "\n").nonEmpty ?? "-").multilineTextAlignment(.trailing) }
                    LabeledContent("地点") { Text(course.locations.joined(separator: "\n").nonEmpty ?? "-").multilineTextAlignment(.trailing) }
                }
                Section("课程标识") {
                    LabeledContent("课程号") { Text(course.kch ?? "-").font(.body.monospaced()).textSelection(.enabled) }
                    LabeledContent("教学班 ID") { Text(course.jxbId).font(.caption.monospaced()).textSelection(.enabled) }
                    LabeledContent("所属方案", value: course.group ?? "未分配")
                }
                Section("容量") {
                    LabeledContent("已选 / 容量", value: course.seatText)
                    LabeledContent("评价更新", value: course.rating.updatedAt ?? "-")
                }
            }
            .formStyle(.grouped)
        } else {
            EmptyHint(title: "选择课程查看详情", symbol: "book.closed", message: "双击课程可加入当前方案")
        }
    }
}

extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}

// MARK: - 方案编辑

private struct PlanEditor: View {
    @Environment(AppStore.self) private var store
    @State private var creating = false
    @State private var newName = ""
    @State private var confirmDelete = false

    var body: some View {
        @Bindable var store = store
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                ScrollView(.horizontal, showsIndicators: false) {
                    GlassGroup(spacing: 8) {
                    HStack(spacing: 8) {
                        ForEach(store.groups) { group in
                            GroupChip(group: group, selected: group.name == store.selectedGroup) {
                                store.selectedGroup = group.name
                                store.memberSelection = []
                            }
                        }
                    }
                    }
                    .padding(.vertical, 4)
                    .padding(.horizontal, 2)
                }
                Button {
                    newName = ""
                    creating = true
                } label: {
                    Label("新建方案", systemImage: "plus")
                }
                .glassButton()
                .popover(isPresented: $creating, arrowEdge: .bottom) {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("新建选课方案").font(.headline)
                        TextField("例如：大学物理", text: $newName)
                            .frame(width: 220)
                            .onSubmit(create)
                        HStack {
                            Spacer()
                            Button("取消") { creating = false }
                            Button("创建", action: create)
                                .keyboardShortcut(.defaultAction)
                                .disabled(newName.trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                    }
                    .padding(14)
                }
                if store.groupsDirty {
                    Button("放弃修改") { store.revertGroups() }
                        .glassButton()
                }
                Button("保存方案") { Task { await store.saveGroups() } }
                    .keyboardShortcut("s")
                    .glassButton(prominent: true)
                    .disabled(!store.groupsDirty || store.busy)
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 6)
            if let index = store.selectedGroupIndex {
                HStack(spacing: 0) {
                    PriorityList(group: store.groups[index])
                    controls(store.groups[index])
                        .frame(width: 200)
                        .padding(14)
                }
            } else {
                EmptyHint(title: "尚未创建选课方案", symbol: "list.number",
                          message: "新建方案后，从上方课程目录双击或右键加入教学班")
            }
        }
        .confirmationDialog("删除方案“\(store.selectedGroup ?? "")”？", isPresented: $confirmDelete) {
            Button("删除", role: .destructive) { store.deleteSelectedGroup() }
        } message: {
            Text("保存后该方案及其优先级配置将被移除。")
        }
    }

    private func controls(_ group: PriorityGroup) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Toggle("体育课方案", isOn: Binding(get: { group.isPe }, set: { store.setPE($0) }))
                .toggleStyle(.switch)
                .controlSize(.small)
            Button {
                let ids = store.filteredCourses.map(\.jxbId).filter(store.courseSelection.contains)
                Task {
                    if let warning = await store.addCourses(ids) {
                        store.notice = Notice(title: "时间冲突提示", message: warning)
                    }
                }
            } label: {
                Label("加入所选 (\(store.courseSelection.count))", systemImage: "plus")
                    .frame(maxWidth: .infinity)
            }
            .glassButton(prominent: !store.courseSelection.isEmpty)
            .disabled(store.courseSelection.isEmpty)
            GlassGroup(spacing: 6) {
                VStack(spacing: 6) {
                    HStack(spacing: 6) {
                        Button { store.moveSelectedMember(by: -1) } label: {
                            Image(systemName: "arrow.up").frame(maxWidth: .infinity)
                        }
                        .help("上移")
                        .glassButton()
                        Button { store.moveSelectedMember(by: 1) } label: {
                            Image(systemName: "arrow.down").frame(maxWidth: .infinity)
                        }
                        .help("下移")
                        .glassButton()
                    }
                    .disabled(store.memberSelection.count != 1)
                    Button {
                        if let id = store.memberSelection.first { store.setAsHeld(id) }
                    } label: {
                        Label("设为当前持有", systemImage: "pin").frame(maxWidth: .infinity)
                    }
                    .glassButton()
                    .disabled(store.memberSelection.count != 1)
                    Button {
                        store.removeMembers(store.memberSelection)
                    } label: {
                        Label("移除所选", systemImage: "minus.circle").frame(maxWidth: .infinity)
                    }
                    .glassButton()
                    .disabled(store.memberSelection.isEmpty)
                }
            }
            Spacer()
            Button(role: .destructive) {
                confirmDelete = true
            } label: {
                Label("删除方案…", systemImage: "trash").frame(maxWidth: .infinity)
            }
            .glassButton()
        }
    }

    private func create() {
        if store.createGroup(named: newName) { creating = false }
    }
}

private struct GroupChip: View {
    @Environment(AppStore.self) private var store
    let group: PriorityGroup
    let selected: Bool
    let action: () -> Void

    var body: some View {
        let conflicts = store.conflicts(for: group).count
        Button(action: action) {
            HStack(spacing: 6) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(group.name).font(.callout.weight(.semibold))
                    Text("\(store.heldLabel(for: group)) · \(group.priority.count) 个")
                        .font(.caption2)
                        .foregroundStyle(selected ? AnyShapeStyle(.white.opacity(0.85)) : AnyShapeStyle(.secondary))
                        .lineLimit(1)
                }
                if conflicts > 0 {
                    if selected {
                        Label("\(conflicts)", systemImage: "exclamationmark.triangle.fill")
                            .font(.caption.weight(.semibold))
                            .help("\(conflicts) 个课程与本组外已选冲突，不会被选择")
                    } else {
                        StatusBadge(text: "冲突 \(conflicts)", tone: .danger)
                    }
                }
                if group.fatal { StatusBadge(text: "暂停", tone: selected ? .neutral : .danger) }
            }
            .frame(maxWidth: 240, alignment: .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .foregroundStyle(selected ? AnyShapeStyle(.white) : AnyShapeStyle(.primary))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .glassCapsule(tint: selected ? .accentColor : nil, interactive: true)
    }
}

private struct PriorityList: View {
    @Environment(AppStore.self) private var store
    let group: PriorityGroup

    var body: some View {
        @Bindable var store = store
        let marks = store.conflicts(for: group)
        let byId = store.coursesById
        List(selection: $store.memberSelection) {
            ForEach(Array(group.priority.enumerated()), id: \.element) { index, id in
                let course = byId[id]
                let mark = marks[id]
                HStack(alignment: .top, spacing: 10) {
                    Text("\(index + 1)")
                        .font(.callout.monospacedDigit().weight(.semibold))
                        .foregroundStyle(.secondary)
                        .frame(width: 22, alignment: .trailing)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(course.map { "\($0.title) · \($0.className)" } ?? AppStore.shortId(id))
                            .lineLimit(1)
                        Text(course?.summary ?? id)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                        if let mark {
                            Text(mark.note).font(.caption).foregroundStyle(.red)
                        }
                    }
                    Spacer()
                    if course?.chosen == true {
                        StatusBadge(text: "当前持有", tone: .accent)
                    } else if let mark {
                        StatusBadge(text: mark.badge, tone: .danger)
                    } else if let course {
                        StatusBadge(text: course.availabilityText, tone: course.statusTone)
                    }
                }
                .padding(.vertical, 2)
                .tag(id)
                .contextMenu {
                    Button("设为当前持有") { store.setAsHeld(id) }
                    Button("从方案移除") { store.removeMembers([id]) }
                }
            }
            .onMove { store.moveMembers(from: $0, to: $1) }
        }
        .scrollContentBackground(.hidden)
        .onDeleteCommand { store.removeMembers(store.memberSelection) }
        .overlay {
            if group.priority.isEmpty {
                EmptyHint(title: "方案为空", symbol: "tray", message: "优先级从上到下；当前持有的教学班固定在末尾")
            }
        }
    }
}
