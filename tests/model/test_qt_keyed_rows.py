"""The native Qt keyed container keeps its row objects and reader state."""

from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem
from toad.qt.window import TreeItemRows


def test_native_qt_row_batches_preserve_identity_order_and_selection(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    tree=QTreeWidget()
    class Parent(QTreeWidgetItem):
        def __init__(self):
            super().__init__(tree)
            self.batches=[]
        def addChildren(self,rows):
            rows=tuple(rows); self.batches.append(rows); super().addChildren(rows)
    class Row(QTreeWidgetItem):
        def __init__(self,key):
            super().__init__([key]); self.placements=0; self.retirements=0
            self.addChild(QTreeWidgetItem(['nested']))
        def placed(self):
            assert self.parent() is parent
            self.placements+=1
        def subtree(self):
            yield self
        def retired(self): self.retirements+=1
    class Group(TreeItemRows[str]):
        def __init__(self,parent): self.parent=parent; self.rows={}
        def create_row(self,key): return Row(key)

    parent=Parent(); group=Group(parent)
    keys=tuple(f'row-{i}' for i in range(40))
    group.reconcile_keys(keys,changed=frozenset())
    assert len(parent.batches)==1
    assert all(row.placements==1 for row in group.rows.values())
    original=dict(group.rows); selected=original['row-24']; selected.setExpanded(True); selected.setSelected(True)
    keys=('first',*reversed(keys[15:]),'last')
    group.reconcile_keys(keys,changed=frozenset({'row-24'}))
    assert len(parent.batches)==2 and len(parent.batches[1])==2
    assert tuple(parent.child(i) for i in range(parent.childCount()))==tuple(group.rows[k] for k in keys)
    assert all(group.rows[k] is original[k] for k in keys if k in original)
    assert selected.isExpanded() and selected.isSelected()
    assert all(row.retirements==1 and row.parent() is None for key,row in original.items() if key not in keys)
    group.reconcile_keys(keys,changed=frozenset())
    assert len(parent.batches)==2
    tree.close(); app.quit()
