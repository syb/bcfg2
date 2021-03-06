"""Django models for Bcfg2 reports."""
from django.db import models
from django.db.models import Q
from datetime import datetime, timedelta
from time import strptime

KIND_CHOICES = (
    #These are the kinds of config elements
    ('Package', 'Package'),
    ('Path', 'directory'),
    ('Path', 'file'),
    ('Path', 'permissions'),
    ('Path', 'symlink'),
    ('Service', 'Service'),
)
PING_CHOICES = (
    #These are possible ping states
    ('Up (Y)', 'Y'),
    ('Down (N)', 'N')
)
TYPE_BAD = 1
TYPE_MODIFIED = 2
TYPE_EXTRA = 3

TYPE_CHOICES = (
    (TYPE_BAD, 'Bad'),
    (TYPE_MODIFIED, 'Modified'),
    (TYPE_EXTRA, 'Extra'),
)
class ClientManager(models.Manager):
    """Extended client manager functions."""
    def active(self, timestamp='now'):
        '''returns a set of clients that have been created and have not yet been
        expired as of optional timestmamp argument. Timestamp should be a
        string formatted in the fashion: 2006-01-01 00:00:00'''
        
        if timestamp == 'now':
            timestamp = datetime.now()
        else:
            print timestamp
            try:
                timestamp = datetime(*strptime(timestamp, "%Y-%m-%d %H:%M:%S")[0:6])
            except ValueError:
                return self.filter(expiration__lt=timestamp, creation__gt=timestamp);
                '''
                - this is a really hacky way to return an empty QuerySet
                - this should return Client.objects.none() in Django
                  development version.
                '''
        
        return self.filter(Q(expiration__gt=timestamp) | Q(expiration__isnull=True),
                           creation__lt=timestamp)


class Client(models.Model):
    """Object representing every client we have seen stats for."""
    creation = models.DateTimeField(auto_now_add=True)
    name = models.CharField(max_length=128,)
    current_interaction = models.ForeignKey('Interaction',
                                            null=True, blank=True,
                                            related_name="parent_client")
    expiration = models.DateTimeField(blank=True, null=True)
    
    def __str__(self):
        return self.name

    objects = ClientManager()
    
    class Admin:
        pass

class Ping(models.Model):
    """Represents a ping of a client (sparsely)."""
    client = models.ForeignKey(Client, related_name="pings")
    starttime = models.DateTimeField()
    endtime = models.DateTimeField()
    status = models.CharField(max_length=4, choices=PING_CHOICES)#up/down

    class Meta:
        get_latest_by = 'endtime'
    
class InteractiveManager(models.Manager):
    """Manages interactions objects.
    
    Returns most recent interaction as of specified timestamp in format:
    '2006-01-01 00:00:00' or 'now' or None->'now'

    """
    def interaction_per_client(self, maxdate = None):
        """Returns the most recent interactions for clients as of a date.
        FIXME - check the dates passed in.
        
        """
        from django.db import connection
        cursor = connection.cursor()

        sql = 'select reports_interaction.id, x.client_id from (select client_id, MAX(timestamp) ' + \
                    'as timer from reports_interaction'
        if maxdate != 'now':
            sql = sql + " where timestamp < '%s' " % maxdate
        sql = sql + ' GROUP BY client_id) x, reports_interaction where ' + \
                    'reports_interaction.client_id = x.client_id AND reports_interaction.timestamp = x.timer'
        try:
            cursor.execute(sql)
        except:
            '''FIXME - really need some error hadling'''
            return self.none()
        return self.filter(id__in = [item[0] for item in cursor.fetchall()])


class Interaction(models.Model):
    """Models each reconfiguration operation interaction between client and server."""
    client = models.ForeignKey(Client, related_name="interactions",)
    timestamp = models.DateTimeField()#Timestamp for this record
    state = models.CharField(max_length=32)#good/bad/modified/etc
    repo_rev_code = models.CharField(max_length=64)#repo revision at time of interaction
    client_version = models.CharField(max_length=32)#Client Version
    goodcount = models.IntegerField()#of good config-items
    totalcount = models.IntegerField()#of total config-items
    server = models.CharField(max_length=256)    # Name of the server used for the interaction
    bad_entries = models.IntegerField(default=-1)
    modified_entries = models.IntegerField(default=-1)
    extra_entries = models.IntegerField(default=-1)

    def __str__(self):
        return "With " + self.client.name + " @ " + self.timestamp.isoformat()

    def percentgood(self):
        if not self.totalcount == 0:
            return (self.goodcount/float(self.totalcount))*100
        else:
            return 0

    def percentbad(self):
        if not self.totalcount == 0:
            return ((self.totalcount-self.goodcount)/(float(self.totalcount)))*100
        else:
            return 0
    
    def isclean(self):
        if (self.bad_entry_count() == 0 and self.goodcount == self.totalcount):
            return True
        else:
            return False
        
    def isstale(self):
        if (self == self.client.current_interaction):#Is Mostrecent
            if(datetime.now()-self.timestamp > timedelta(hours=25) ):
                return True
            else:
                return False
        else:
            #Search for subsequent Interaction for this client
            #Check if it happened more than 25 hrs ago.
            if (self.client.interactions.filter(timestamp__gt=self.timestamp)
                    .order_by('timestamp')[0].timestamp -
                    self.timestamp > timedelta(hours=25)):
                return True
            else:
                return False
    def save(self):
        super(Interaction, self).save() #call the real save...
        self.client.current_interaction = self.client.interactions.latest()
        self.client.save()#save again post update

    def badcount(self):
        return self.totalcount - self.goodcount

    def bad(self):
        return Entries_interactions.objects.select_related().filter(interaction=self, type=TYPE_BAD)

    def bad_entry_count(self):
        """Number of bad entries.  Store the count in the interation field to save db queries."""
        if self.bad_entries < 0:
            self.bad_entries = Entries_interactions.objects.filter(interaction=self, type=TYPE_BAD).count()
            self.save()
        return self.bad_entries

    def modified(self):
        return Entries_interactions.objects.select_related().filter(interaction=self, type=TYPE_MODIFIED)

    def modified_entry_count(self):
        """Number of modified entries.  Store the count in the interation field to save db queries."""
        if self.modified_entries < 0:
            self.modified_entries = Entries_interactions.objects.filter(interaction=self, type=TYPE_MODIFIED).count()
            self.save()
        return self.modified_entries

    def extra(self):
        return Entries_interactions.objects.select_related().filter(interaction=self, type=TYPE_EXTRA)

    def extra_entry_count(self):
        """Number of extra entries.  Store the count in the interation field to save db queries."""
        if self.extra_entries < 0:
            self.extra_entries = Entries_interactions.objects.filter(interaction=self, type=TYPE_EXTRA).count()
            self.save()
        return self.extra_entries
    
    objects = InteractiveManager()

    class Admin:
        list_display = ('client', 'timestamp', 'state')
        list_filter = ['client', 'timestamp']
        pass
    class Meta:
        get_latest_by = 'timestamp'
        unique_together = ("client", "timestamp")

class Reason(models.Model):
    """reason why modified or bad entry did not verify, or changed."""
    owner = models.TextField(max_length=128, blank=True)
    current_owner = models.TextField(max_length=128, blank=True)
    group = models.TextField(max_length=128, blank=True)
    current_group = models.TextField(max_length=128, blank=True)
    perms =  models.TextField(max_length=4, blank=True)#txt fixes typing issue
    current_perms = models.TextField(max_length=4, blank=True)
    status = models.TextField(max_length=3, blank=True)#on/off/(None)
    current_status = models.TextField(max_length=1, blank=True)#on/off/(None)
    to = models.TextField(max_length=256, blank=True)
    current_to = models.TextField(max_length=256, blank=True)
    version = models.TextField(max_length=128, blank=True)
    current_version = models.TextField(max_length=128, blank=True)
    current_exists = models.BooleanField()#False means its missing. Default True
    current_diff = models.TextField(max_length=1280, blank=True)
    is_binary = models.BooleanField(default=False)
    def _str_(self):
        return "Reason"

class Entries(models.Model):
    """Contains all the entries feed by the client."""
    name = models.CharField(max_length=128, db_index=True)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, db_index=True)

    def __str__(self):
        return self.name

class Entries_interactions(models.Model):
    """Define the relation between the reason, the interaction and the entry."""
    entry = models.ForeignKey(Entries)
    reason = models.ForeignKey(Reason)
    interaction = models.ForeignKey(Interaction)
    type = models.IntegerField(choices=TYPE_CHOICES)
    
class PerformanceManager(models.Manager):
    """
    Provides ability to effectively query for performance information
    It is possible this should move to the view

    """
    #Date format for maxdate: '2006-01-01 00:00:00'            
    def performance_per_client(self, maxdate = None):
        from django.db import connection
        cursor = connection.cursor()
        if (maxdate == 'now' or maxdate == None):
            cursor.execute("SELECT reports_client.name, reports_performance.metric, reports_performance.value "+
            "FROM reports_performance, reports_performance_interaction, reports_client WHERE ( "+
            "reports_client.current_interaction_id = reports_performance_interaction.interaction_id AND "+
            "reports_performance.id = reports_performance_interaction.performance_id)")
        else:
            cursor.execute("select reports_client.name, reports_performance.metric, "+
                           "reports_performance.value from (Select reports_interaction.client_id as client_id, "+
                           "MAX(reports_interaction.timestamp) as timestamp from reports_interaction where "+
                           "timestamp < %s GROUP BY reports_interaction.client_id) x, reports_client, "+
                           "reports_interaction, reports_performance, reports_performance_interaction where "+
                           "reports_client.id = x.client_id AND x.timestamp = reports_interaction.timestamp AND "+
                           "x.client_id = reports_interaction.client_id AND reports_performance.id = "+
                           "reports_performance_interaction.performance_id AND "+
                           "reports_performance_interaction.interaction_id = reports_interaction.id", [maxdate])

        results = {}
        for row in cursor.fetchall():
            try:
                results[row[0]].__setitem__(row[1], row[2])
            except KeyError:
                results[row[0]] = {row[1]:row[2]}
                                
        return results
    
#performance metrics, models a performance-metric-item
class Performance(models.Model):
    """Object representing performance data for any interaction."""
    interaction = models.ManyToManyField(Interaction, related_name="performance_items")
    metric = models.CharField(max_length=128)
    value = models.DecimalField(max_digits=32, decimal_places=16)
    def __str__(self):
        return self.metric
 
    objects = PerformanceManager()
 
class InternalDatabaseVersion(models.Model):
    """Object that tell us to witch version is the database."""
    version = models.IntegerField()
    updated = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return "version %d updated the %s" % (self.version, self.updated.isoformat())
