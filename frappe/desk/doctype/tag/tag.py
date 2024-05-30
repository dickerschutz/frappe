# Copyright (c) 2019, Frappe Technologies and contributors
# License: MIT. See LICENSE

import frappe
import json
from frappe.model.document import Document
from frappe.query_builder import DocType
from frappe.utils import unique



class Tag(Document):

	def after_rename(self, old: str, new: str, merge: bool = False):
		for doctype, record in _iter_user_tagged_records():
			record_tags = record["_user_tags"]

			try:
				record_tags = json.loads(record_tags)
			except Exception as ex:
				record_tags = None

			record_tags = list(record_tags)
			if old  not in record_tags:
				continue

			record_tags[record_tags.index(old)] = new
			record_tags = sorted(tag for tag in set(record_tags))
			frappe.db.set_value(doctype, record["name"], "_user_tags", json.dumps(record_tags))




def check_user_tags(dt):
	"if the user does not have a tags column, then it creates one"
	try:
		doctype = DocType(dt)
		frappe.qb.from_(doctype).select(doctype._user_tags).limit(1).run()
	except Exception as e:
		if frappe.db.is_column_missing(e):
			DocTags(dt).setup()


@frappe.whitelist()
def add_tag(tag, dt, dn, color=None):
	"adds a new tag to a record, and creates the Tag master"
	DocTags(dt).add(dn, tag)

	return tag


@frappe.whitelist()
def add_tags(tags, dt, docs, color=None):
	"adds a new tag to a record, and creates the Tag master"
	tags = frappe.parse_json(tags)
	docs = frappe.parse_json(docs)
	for doc in docs:
		for tag in tags:
			DocTags(dt).add(doc, tag)

	# return tag


@frappe.whitelist()
def remove_tag(tag, dt, dn):
	"removes tag from the record"
	DocTags(dt).remove(dn, tag)


@frappe.whitelist()
def get_tagged_docs(doctype, tag):
	frappe.has_permission(doctype, throw=True)
	doctype = DocType(doctype)
	return (frappe.qb.from_(doctype).where(doctype._user_tags.like(tag)).select(doctype.name)).run()


@frappe.whitelist()
def get_tags(doctype, txt):
	tag = frappe.get_list("Tag", filters=[["name", "like", f"%{txt}%"]])
	tags = [t.name for t in tag]

	return sorted(filter(lambda t: t and txt.lower() in t.lower(), list(set(tags))))


class DocTags:
	"""Tags for a particular doctype"""

	def __init__(self, dt):
		self.dt = dt

	def get_tag_fields(self):
		"""returns tag_fields property"""
		return frappe.db.get_value("DocType", self.dt, "tag_fields")

	def get_tags(self, dn):
		"""returns tag for a particular item"""
		return json.loads(frappe.db.get_value(self.dt, dn, "_user_tags", ignore=1) or "[]")

	def add(self, dn, tag):
		"""add a new user tag"""
		tl = self.get_tags(dn)
		if not tag in tl:
			tl.append(tag)
			if not frappe.db.exists("Tag", tag):
				frappe.get_doc({"doctype": "Tag", "name": tag}).insert(ignore_permissions=True)
			self.update(dn, tl)

	def remove(self, dn, tag):
		"""remove a user tag"""
		tl = self.get_tags(dn)
		self.update(dn, filter(lambda x: x.lower() != tag.lower(), tl))

	def remove_all(self, dn):
		"""remove all user tags (call before delete)"""
		self.update(dn, [])

	def update(self, dn, tl):
		"""updates the _user_tag column in the table"""

		if not tl:
			tags = []
		else:
			tags = unique(filter(lambda x: x, tl))
		try:
			frappe.db.sql(
				"update `tab{}` set _user_tags={} where name={}".format(self.dt, "%s", "%s"), (json.dumps(tags), dn)
			)
			doc = frappe.get_doc(self.dt, dn)
			update_tags(doc, tags)
		except Exception as e:
			if frappe.db.is_column_missing(e):
				if not tags:
					# no tags, nothing to do
					return

				self.setup()
				self.update(dn, tl)
			else:
				raise

	def setup(self):
		"""adds the _user_tags column if not exists"""
		from frappe.database.schema import add_column

		add_column(self.dt, "_user_tags", frappe.db.STANDARD_FIELD_CONVERSION_MAP["_user_tags"])


def delete_tags_for_document(doc):
	"""
	Delete the Tag Link entry of a document that has
	been deleted
	:param doc: Deleted document
	"""
	if not frappe.db.table_exists("Tag Link"):
		return

	frappe.db.delete("Tag Link", {"document_type": doc.doctype, "document_name": doc.name})


def update_tags(doc, tags):
	"""Adds tags for documents

	:param doc: Document to be added to global tags
	"""
	new_tags = set(tags)
	existing_tags = [
		tag.tag
		for tag in frappe.get_list(
			"Tag Link", filters={"document_type": doc.doctype, "document_name": doc.name}, fields=["tag"]
		)
	]
	added_tags = set(new_tags) - set(existing_tags)
	for tag in added_tags:
		frappe.get_doc(
			{
				"doctype": "Tag Link",
				"document_type": doc.doctype,
				"document_name": doc.name,
				"title": doc.get_title() or "",
				"tag": tag,
			}
		).insert(ignore_permissions=True)

	deleted_tags = list(set(existing_tags) - set(new_tags))
	for tag in deleted_tags:
		frappe.db.delete(
			"Tag Link", {"document_type": doc.doctype, "document_name": doc.name, "tag": tag}
		)


@frappe.whitelist()
def get_documents_for_tag(tag):
	"""
	Search for given text in Tag Link
	:param tag: tag to be searched
	"""
	# remove hastag `#` from tag
	tag = tag[1:]
	results = []

	result = frappe.get_list(
		"Tag Link", filters={"tag": tag}, fields=["document_type", "document_name", "title", "tag"]
	)

	for res in result:
		results.append({"doctype": res.document_type, "name": res.document_name, "content": res.title})

	return results


@frappe.whitelist()
def get_tags_list_for_awesomebar():
	return [t.name for t in frappe.get_list("Tag")]



def _iter_user_tagged_records():
	doctypes = [doctype["name"] for doctype in frappe.db.get_list("DocType")]
	for doctype in doctypes:
		try:
			records = frappe.db.get_list(doctype, fields=["name", "_user_tags"], filters=[("_user_tags","is", "set")])
		except Exception:
			continue

		for record in records:
			if "_user_tags" not in record:
				continue

			yield doctype, record


def cleanup_tags():
	tags = set(tag["name"] for tag in frappe.db.get_list("Tag"))
	for doctype, record in _iter_user_tagged_records():
			record_tags = record["_user_tags"]

			try:
				record_tags = json.loads(record_tags)
			except Exception as ex:
				record_tags = None

			record_tags = sorted(tag for tag in record_tags if tag in tags)
			frappe.db.set_value(doctype, record["name"], "_user_tags", json.dumps(record_tags))




