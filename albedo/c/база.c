// SQLite усередині модуля (Альбедо, spec/пропозиції/альбедо.md §2): рушій бази — за межею разом з ядром, а його файли — через
// імпорт ngr.db, і який файл взагалі можна відкрити, вирішує господар за печаткою. ATTACH на чужу базу впирається не в сторожа в
// sqlite.rs (той теж на місці), а в господаря. Блокувань немає: двох записувачів з іншими процесами Альбедо не тримає (§3).
#include "sqlite3.c"
#include "expat.h"

__attribute__((import_module("ngr"), import_name("db")))
extern long long ngr_db(int op, long long a, long long b, void *p, int n);
__attribute__((import_module("ngr"), import_name("random"))) extern void ngr_random(void *p, int n);
__attribute__((import_module("ngr"), import_name("now"))) extern long long ngr_now(void);

// WAL без спільної памʼяті: SQLITE_DEFAULT_LOCKING_MODE=1 тримає його індекс у купі, а блокувань тут немає все одно (§3)
#define RO_BIT (1LL << 30)
enum { DB_OPEN = 1, DB_READ, DB_WRITE, DB_SIZE, DB_TRUNC, DB_SYNC, DB_CLOSE, DB_DELETE, DB_ACCESS };

typedef struct { sqlite3_file base; int h; } F;

static int f_close(sqlite3_file *f) { ngr_db(DB_CLOSE, ((F *)f)->h, 0, 0, 0); return SQLITE_OK; }
static int f_read(sqlite3_file *f, void *b, int n, sqlite3_int64 off) {
  long long r = ngr_db(DB_READ, ((F *)f)->h, off, b, n);
  if (r < 0) return SQLITE_IOERR_READ;
  if (r < n) { memset((char *)b + r, 0, n - r); return SQLITE_IOERR_SHORT_READ; }
  return SQLITE_OK;
}
static int f_write(sqlite3_file *f, const void *b, int n, sqlite3_int64 off) {
  return ngr_db(DB_WRITE, ((F *)f)->h, off, (void *)b, n) == n ? SQLITE_OK : SQLITE_IOERR_WRITE;
}
static int f_trunc(sqlite3_file *f, sqlite3_int64 n) { return ngr_db(DB_TRUNC, ((F *)f)->h, n, 0, 0) < 0 ? SQLITE_IOERR_TRUNCATE : SQLITE_OK; }
static int f_sync(sqlite3_file *f, int fl) { return ngr_db(DB_SYNC, ((F *)f)->h, 0, 0, 0) < 0 ? SQLITE_IOERR_FSYNC : SQLITE_OK; }
static int f_size(sqlite3_file *f, sqlite3_int64 *n) { long long r = ngr_db(DB_SIZE, ((F *)f)->h, 0, 0, 0); if (r < 0) return SQLITE_IOERR_FSTAT; *n = r; return SQLITE_OK; }
static int f_lock(sqlite3_file *f, int l) { return SQLITE_OK; }
static int f_reserved(sqlite3_file *f, int *r) { *r = 0; return SQLITE_OK; }
static int f_control(sqlite3_file *f, int op, void *a) { return SQLITE_NOTFOUND; }
static int f_sector(sqlite3_file *f) { return 4096; }
static int f_caps(sqlite3_file *f) { return 0; }
static const sqlite3_io_methods METHODS = { 1, f_close, f_read, f_write, f_trunc, f_sync, f_size, f_lock, f_lock, f_reserved, f_control, f_sector, f_caps };

static int v_open(sqlite3_vfs *v, const char *name, sqlite3_file *f, int flags, int *out) {
  f->pMethods = 0;
  if (!name) return SQLITE_CANTOPEN;             // тимчасове — лише в памʼяті: SQLITE_TEMP_STORE=3
  long long h = ngr_db(DB_OPEN, (flags & SQLITE_OPEN_READWRITE) ? ((flags & SQLITE_OPEN_CREATE) ? 2 : 1) : 0, 0, (void *)name, strlen(name));
  if (h < 0) return h == -13 ? SQLITE_PERM : SQLITE_CANTOPEN;
  int ro = (h & RO_BIT) != 0;                    // WAL під «бд.читати»: просив запис, господар дав читання (сам SQLite завжди просить запис)
  ((F *)f)->h = (int)(h & ~RO_BIT);
  f->pMethods = &METHODS;
  if (out) *out = ro ? (flags & ~(SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE)) | SQLITE_OPEN_READONLY : flags;
  return SQLITE_OK;
}
static int v_delete(sqlite3_vfs *v, const char *name, int sync) {
  long long r = ngr_db(DB_DELETE, 0, 0, (void *)name, strlen(name));
  return r == 0 || r == -2 ? SQLITE_OK : SQLITE_IOERR_DELETE;
}
static int v_access(sqlite3_vfs *v, const char *name, int what, int *out) {
  long long r = ngr_db(DB_ACCESS, what, 0, (void *)name, strlen(name));
  *out = r > 0;
  return SQLITE_OK;
}
static int v_full(sqlite3_vfs *v, const char *name, int n, char *out) { sqlite3_snprintf(n, out, "%s", name); return SQLITE_OK; }
static int v_random(sqlite3_vfs *v, int n, char *out) { ngr_random(out, n); return n; }
static int v_sleep(sqlite3_vfs *v, int us) { return us; }
static int v_now64(sqlite3_vfs *v, sqlite3_int64 *out) { long long s = ngr_now(); *out = 210866760000000LL + (s < 0 ? 0 : s) * 1000; return SQLITE_OK; }
static int v_now(sqlite3_vfs *v, double *out) { sqlite3_int64 t; v_now64(v, &t); *out = t / 86400000.0; return SQLITE_OK; }
static int v_err(sqlite3_vfs *v, int n, char *out) { return 0; }

static sqlite3_vfs VFS = { 2, sizeof(F), 1024, 0, "ngr", 0, v_open, v_delete, v_access, v_full, 0, 0, 0, 0, v_random, v_sleep, v_now, v_err, v_now64 };
int sqlite3_os_init(void) { return sqlite3_vfs_register(&VFS, 1); }
int sqlite3_os_end(void) { return SQLITE_OK; }

// dlsym ядра: sqlite.rs і xml.rs у модулі беруть ті самі функції, що нативно з libsqlite3 і libexpat, лише зі своєї таблиці
#define S(n) { #n, (void *)n },
static const struct { const char *name; void *p; } SYMS[] = {
  S(sqlite3_bind_blob) S(sqlite3_bind_double) S(sqlite3_bind_int64) S(sqlite3_bind_null) S(sqlite3_bind_parameter_count) S(sqlite3_bind_text)
  S(sqlite3_busy_timeout) S(sqlite3_close_v2) S(sqlite3_column_blob) S(sqlite3_column_bytes) S(sqlite3_column_count) S(sqlite3_column_double)
  S(sqlite3_column_int64) S(sqlite3_column_name) S(sqlite3_column_text) S(sqlite3_column_type) S(sqlite3_create_function_v2) S(sqlite3_data_count)
  S(sqlite3_errcode) S(sqlite3_errmsg) S(sqlite3_errstr) S(sqlite3_finalize) S(sqlite3_get_autocommit) S(sqlite3_limit) S(sqlite3_open_v2)
  S(sqlite3_prepare_v2) S(sqlite3_progress_handler) S(sqlite3_result_blob) S(sqlite3_result_double) S(sqlite3_result_error) S(sqlite3_result_int64)
  S(sqlite3_result_null) S(sqlite3_result_text) S(sqlite3_set_authorizer) S(sqlite3_step) S(sqlite3_total_changes64) S(sqlite3_user_data)
  S(sqlite3_value_blob) S(sqlite3_value_bytes) S(sqlite3_value_double) S(sqlite3_value_int64) S(sqlite3_value_text) S(sqlite3_value_type)
  S(sqlite3_libversion_number) S(sqlite3_extended_errcode)
  S(XML_ErrorString) S(XML_GetCurrentColumnNumber) S(XML_GetCurrentLineNumber) S(XML_GetErrorCode) S(XML_Parse) S(XML_ParserCreateNS) S(XML_ParserFree)
  S(XML_SetCharacterDataHandler) S(XML_SetElementHandler) S(XML_SetEncoding) S(XML_SetEntityDeclHandler) S(XML_SetStartDoctypeDeclHandler)
  S(XML_SetUserData) S(XML_StopParser)
};
void *ngr_sym(const char *name) {
  for (size_t i = 0; i < sizeof SYMS / sizeof SYMS[0]; i++) if (!strcmp(SYMS[i].name, name)) return SYMS[i].p;
  return 0;
}
